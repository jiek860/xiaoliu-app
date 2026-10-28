# -*- coding: utf-8 -*-
"""Trunk 启动预热、备份、后台队列和资源回收。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
import weakref
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


# ---- 活着的躯干登记表（2026-10-28）----------------------------------------
# 为什么要登记：`Trunk.__init__` 无条件起 3 个 `while True` 后台线程
# （`_bg_loop` / `_idle_worker` / `_auto_unload_loop`）。线程持有 self 的绑定方法，
# 于是**躯干本身永远不会被回收**，而 `shutdown()` 只写了一行"停线程"、
# 实际一个都没停（没有停止标志，循环里也没有出口）。
#
# 实测后果：每造一个 Trunk 留下 3 个常驻线程。全量测试累积到 129 个线程后开始报
# `can't start new thread` / `WinError 1455 页面文件太小`，2026-10-13 还崩过一次
# access violation（当时把锅算在 40 个线程上，其实是同一件事）。
# 登记 + `stop_background()` 让"造了有人收"成为可能：shutdown 和测试收尾都调它。
_LIVE_TRUNKS = weakref.WeakSet()
_LIVE_LOCK = threading.Lock()


def register_live(obj):
    """登记一个刚起来、还带着后台线程的躯干"""
    with _LIVE_LOCK:
        _LIVE_TRUNKS.add(obj)


def unregister_live(obj):
    """注销（后台线程已经停了，不再需要收尾）"""
    with _LIVE_LOCK:
        _LIVE_TRUNKS.discard(obj)


def live_trunks():
    """当前还登记着的躯干（测试收尾用；返回的是快照，可安全边遍历边停）"""
    with _LIVE_LOCK:
        return list(_LIVE_TRUNKS)


class TrunkBackgroundMixin:
    # ------------------------------------------------------------------ 停止
    def _stopped(self):
        """本躯干是否已被要求停下（没有 _stop_event 的老对象/测试桩恒为 False）"""
        ev = getattr(self, "_stop_event", None)
        return bool(ev is not None and ev.is_set())

    def _wait(self, seconds):
        """可被 stop_background() 打断的 sleep；返回 True 表示已经该停了"""
        ev = getattr(self, "_stop_event", None)
        if ev is None:
            time.sleep(seconds)
            return False
        return ev.wait(seconds)

    def stop_background(self):
        """让本躯干起的后台线程真正退出（shutdown / 测试收尾都走这里）。

        为什么需要单列一个方法：这些线程都是 `while True`，以前唯一的出口是
        "队列里收到 None 哨兵"或进程退出 —— 而 `shutdown()` 只写了句"停线程"，
        既没 set 标志也没塞哨兵，**一个都没停**。同一个进程里再造躯干（启动失败
        重试、测试造了成百上千个）时线程就一路累积。

        幂等：重复调用只是再 set 一次事件、再塞两个哨兵。
        """
        ev = getattr(self, "_stop_event", None)
        if ev is not None:
            ev.set()
        # 还在倒计时的预热定时器要 cancel：它到点会去 load llm 并拉起看门狗
        timer = getattr(self, "_llm_timer", None)
        if timer is not None:
            try:
                timer.cancel()
            # 静默是故意的：定时器已经跑完/被取消过都不影响退出
            except Exception as e:
                _x6_swallowed(__name__, e, "cancel warmup timer")
            self._llm_timer = None
        # 光设标志不够：两个 worker 可能正卡在 get() 上，塞 None 让它们立刻醒
        for qname in ("_bg_queue", "_idle_queue"):
            q = getattr(self, qname, None)
            try:
                if q is not None:
                    q.put_nowait(None)
            # 静默是故意的：队列满/已关闭都不影响"要求停止"这件事本身
            except Exception as e:
                _x6_swallowed(__name__, e, "stop background queue")
        unregister_live(self)
        # 已登记但还没 start 的后台线程（_start_background/_warmup）会在 wait 时看到标志
        return {"已停止": True}

    def _start_llm_workers_later(self, delay=1.0):
        """延迟启动 LLM 看门狗和模型预热。

        以前这两件事写在 LLMClient.__init__ 里 —— 而 LLMClient 是启动阶段
        并行加载的核心模块之一，它的预热会立刻发网络请求、占 CPU，
        和 GUI 首帧抢时间。现在挪到启动之后，行为不变、启动更快。
        """
        def _run():
            try:
                llm = self.modules.get("llm")
                if llm is None:
                    return
                if hasattr(llm, "start_background_workers"):
                    llm.start_background_workers()
                warm = getattr(llm, "_warmup", None)
                if callable(warm):
                    warm()
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")

        try:
            # ⚠️ threading.Timer 默认 daemon=False —— 进程会等它跑完才退出。
            #    实测：关闭主窗口后线程数停在 7 不下降，其中一个就是这里的
            #    Timer（Thread-7, daemon=False）。预热只是"尽快开始"，
            #    不需要阻止退出，必须显式设成 daemon。
            timer = threading.Timer(max(0.0, float(delay)), _run)
            timer.daemon = True
            timer.name = "llm-warmup-timer"
            timer.start()
            # 留引用：退出时能 cancel 掉还没到点的预热（否则关窗后 1 秒
            # 它又会把 LLM 看门狗拉起来，见 stop_background）
            self._llm_timer = timer
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _init_pipeline(self):
        # 尝试初始化 pipeline；初始化就失败的话只能一直走 legacy
        self._use_pipeline = True
        # pipeline 出错后的冷却重试状态（见 _reply_inner / _pipeline_failed）
        self._pipeline_fail_count = 0     # 连续失败次数，成功一次就清零
        self._pipeline_retry_at = 0.0     # 早于这个时间点不重试 pipeline
        try:
            from core.pipeline import ReplyPipeline
            self._pipeline = ReplyPipeline(self)
            self._log("Pipeline 初始化成功")
        except Exception as e:
            self._use_pipeline = False
            self._pipeline = None
            self._log(f"Pipeline 初始化失败，使用旧流程: {e}")
        # 后台自我改进组件（全try包裹，坏了不影响主程序）
        try:
            from core.config_healer import ConfigHealer
            fixes = ConfigHealer(self).check_and_heal()
            if fixes: self._log(f"配置自愈完成，修复{len(fixes)}项")
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            from core.module_health import ModuleHealth
            disabled = ModuleHealth(self).disabled_modules()
            if disabled: self._log(f"已自动禁用坏模块: {disabled}")
        except Exception as e:
            _x6_swallowed(__name__, e)
        self._log("躯干启动")

    def _warmup(self):
        """预热：后台加载 Ollama 模型 + 向量库，不阻塞启动"""
        try:
            if self._wait(2):        # 2 秒内被要求退出就别再去请求网络了
                return
            try:
                import requests
                url = self.config.get("ollama_url", "http://localhost:11434")
                model = self.config.get("local_model", "qwen2.5:7b")
                requests.post(url + "/api/generate", json={"model": model, "prompt": "", "stream": False}, timeout=30)
                self._log("Ollama warmup done")
            except Exception as e:
                self._log("Ollama warmup skip: %s" % str(e)[:40])
            try:
                self._load_lazy("vector_store")
                self._log("Vector store warmup done")
            except Exception as e:
                self._log("Vector warmup skip: %s" % str(e)[:40])
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _start_background(self):
        """P2-4: 延迟3秒启动后台服务，不阻塞UI（实现在 core/trunk_startup.py）"""
        from core.trunk_startup import start_background
        return start_background(self)

    _AUTO_BACKUP_MIN_GAP_H = 6

    def _auto_backup(self):
        """启动时自动备份一次（实现在 core/trunk_maintenance.py：带节流，走真备份系统）"""
        from core.trunk_maintenance import auto_backup
        return auto_backup(self)

    def _backup_is_recent(self, path):
        """最近的备份是否还在节流窗口内"""
        from core.trunk_maintenance import backup_is_recent
        return backup_is_recent(self, path)

    def _warmup_ollama(self):
        from core.self_check import warmup_ollama
        return warmup_ollama(self)

    def _check_ollama(self):
        from core.self_check import check_ollama
        return check_ollama(self)

    def _check_cloud(self):
        from core.self_check import check_cloud
        return check_cloud(self)

    def _health_score(self):
        from core.self_check import health_score
        return health_score(self)

    def _deep_check(self):
        from core.self_check import deep_check
        return deep_check(self)

    def _auto_unload_loop(self):
        """每 30 秒卸掉 5 分钟没用过的模块（实现在 core/trunk_maintenance.py）"""
        from core.trunk_maintenance import auto_unload_loop
        return auto_unload_loop(self)

    def _bg_loop(self):
        """P0-4: 后台任务单线程工作循环"""
        import queue as _q
        while not self._stopped():
            run_id = ""
            # 用带超时的 get：这样 stop_background() 一 set 标志，最多半秒就退出
            # （以前是无限阻塞 get，只有塞 None 才能醒，关窗/测试收尾时全都留着）
            try:
                task = self._bg_queue.get(timeout=0.5)
            except _q.Empty:
                continue
            except Exception as e:  # 静默是故意的 - 队列被关掉就只能退出
                self._log("后台任务队列异常: %s" % str(e)[:80])
                break
            try:
                if task is None:
                    break
                user_input, answer = task
                try:
                    from core.agent_harness import get_run_registry
                    run_id = "bg:" + str(int(time.time() * 1000))
                    get_run_registry().start_run(
                        "background", "后台处理：%s" % str(user_input)[:48],
                        run_id=run_id, status="running",
                        metadata={"type": "post_process"})
                except Exception:
                    run_id = ""
                self._bg(user_input, answer)
                if run_id:
                    from core.agent_harness import get_run_registry
                    get_run_registry().finish_run(run_id, "completed")
            except Exception as e:
                self._log("后台任务异常: %s" % str(e)[:80])
                if run_id:
                    try:
                        from core.agent_harness import get_run_registry
                        get_run_registry().finish_run(run_id, "failed", str(e))
                    except Exception as e:  # 静默是故意的
                        _x6_swallowed(__name__, e, "best-effort fallback")
            finally:
                self._bg_queue.task_done()

    def _defer_to_idle(self, fn):
        """把「要调模型」的后处理排到用户空闲之后再做。

        为什么必须排队、不能当场判断：后处理就在回复刚结束那一刻执行，
        那一刻用户必然刚说过话 —— 任何「现在空闲吗」的检查都必然为否。
        原来的 _idle 就是这么恒假了三个星期的，所以这里换成排队等空闲。
        """
        try:
            if self._idle_queue.qsize() > 200:
                self._warn_user("后台整理任务积压过多，跳过一轮")
                return
            self._idle_queue.put(fn)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _idle_worker(self):
        """空闲任务线程：等不忙了再做反思 / 记忆闭环"""
        import queue as _q
        while not self._stopped():
            try:
                # 同样用带超时的 get：否则线程永远卡在 get 上，stop 也收不掉
                try:
                    task = self._idle_queue.get(timeout=0.5)
                except _q.Empty:
                    continue
                if task is None:
                    break
                # 最多等 10 分钟；等不到就放弃这一轮，避免无限积压
                deadline = time.time() + 600
                while self._chat_busy() and time.time() < deadline:
                    if self._wait(5):     # 被要求退出就别再等空闲了
                        return
                if self._chat_busy():
                    # 一直没等到空闲：这轮反思/记忆沉淀就没了，得让用户知道
                    self._warn_user("你聊得太连续，后台整理这轮跳过了")
                    continue
                try:
                    task()
                except Exception as e:
                    self._warn_user("后台整理出错（详情见日志）", e)
                if self._wait(1):         # 任务之间喘口气，别一口气把模型打满
                    return
            except Exception as e:
                self._log("空闲任务线程异常: %s" % str(e)[:80])

    def _bg(self, user_input, answer):
        # P1-21: 隐私模式（无痕会话）不写记忆/向量/日志
        if getattr(self, "_private_mode", False):
            self._log("隐私模式：本次对话不记录")
            return
        try:
            # 存向量
            vs = self.modules.get("vector_store")
            if vs:
                vs.add(user_input, answer)
            # 存知识图谱
            kg = self.modules.get("knowledge_graph")
            if kg:
                kg.add_dialog(user_input, answer)
            # P2-8: 每次回答后轻量自评估（规则粗筛，不占模型，落在
            # data/reflect_history.json —— 注释原来写的是 self_eval.json，
            # 但那个文件全项目没有写入方）
            try:
                _rfl = self.modules.get("self_reflect") or self._load_lazy("self_reflect")
                if _rfl and hasattr(_rfl, "quick_eval"):
                    _rfl.quick_eval(user_input, answer)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            # 反思（降频：每5轮一次）。要调模型，排到用户空闲后做。
            #
            # 这里原来是 `if _idle and ...`，而 _idle 恒为 False：
            # _chat_active_until 在任务入队前一行刚被设成 now+120，而后处理又恰好
            # 在回复刚结束那一刻执行 —— "现在空闲吗"必然为否。反思/记忆闭环/技能捕获
            # 三条链因此静默失效了三个星期（reflections.json 停在 09-23，
            # episodic_memory.json 也停在 09-23）。结论：换采样点没用，只能排队等空闲。
            if getattr(self, "_reply_n", 0) % 5 == 1:
                self._defer_to_idle(
                    lambda ui=user_input, an=answer:
                        self.call("self_reflect", "reflect", ui, an))
            # 拟人：感知用户情绪 + 记住值得以后提的事
            pers = self.modules.get("personality")
            if pers:
                try:
                    pers.sense_feeling(user_input)
                    pers.remember_event(user_input)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            # 记忆卡：由memory_loop内部统一调用，避免重复触发
            # （之前这里单独调一次，ml.run内部又调一次，导致同一轮写2张卡）
            # ===== 闭环自动接线 =====
            # 记忆闭环：对话→记忆卡→遗忘曲线→到期复习→检索增强。
            # 内部会调模型（memory_cards.maybe_summarize），排到空闲后做。
            def _memory_chain(ui=user_input, an=answer):
                try:
                    ml = self._load_lazy("memory_loop")
                    if ml and hasattr(ml, "run"):
                        # C2: 情景记忆直接接线（不依赖记忆闭环内部流程，禁了闭环也不断线）
                        try:
                            if hasattr(ml, "remember_scene"):
                                ml.remember_scene(ui, an)
                        except Exception as e:
                            _x6_swallowed(__name__, e)
                            pass
                        ml.run(ui, an)
                except Exception as e:
                    self._warn_user("记忆沉淀失败（详情见日志）", e)
            self._defer_to_idle(_memory_chain)
            # 技能捕获：任务类对话且产出成功 → 存成 SKILL.md。
            # 两点要注意：
            #   1) capture() 是 skill_capture 的方法，skill_distill 只有 distill()。
            #      原来加载错了模块，又用 hasattr 挡着，于是静默失效了很久
            #      （data/skills/ 最后写入停在 09-22）。
            #   2) 它纯写文件、不调模型，所以不必等空闲，立即执行。
            try:
                kw = ["帮我写", "帮我做", "帮我实现", "写一个", "做一个", "实现一个", "修复", "整理一下"]
                if any(k in user_input for k in kw) and not str(answer).startswith(("（", "抱歉", "出错了")):
                    sc = self._load_lazy("skill_capture")
                    if sc:
                        # confirm=True 直接进正式库：confirm_skill() 全项目没有调用方，
                        # 走 pending 的话技能会永远堆在 data/skills_pending/ 没人确认。
                        sc.capture(user_input, str(answer)[:300], success=True, confirm=True)
            except Exception as e:
                # 故意不用 hasattr 兜底：方法名再改错要能在日志里看见，而不是又静默失踪。
                # 同时给用户一行状态栏提示 —— 技能没沉淀下来是用户能感知的损失。
                self._warn_user("技能捕获失败（详情见日志）", e)
            # 任务闭环：智能路由判断复杂任务（关键词→LLM→缓存），自动拆解执行
            try:
                txt = str(user_input)
                verbs = ["做", "写", "实现", "开发", "设计", "搭建", "整理", "制作", "创建", "生成"]
                if len(txt) >= 8 and any(v in txt for v in verbs):
                    sr = self._load_lazy("smart_router")
                    if sr and hasattr(sr, "route"):
                        r = sr.route(txt)
                        if isinstance(r, dict) and r.get("意图") == "task":
                            tl = self._load_lazy("task_loop")
                            if tl and hasattr(tl, "run"):
                                tr = tl.run(txt[:150])
                                self._log("任务闭环(智能路由): %s" % str(tr.get("ok", tr))[:60])
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        except Exception as e:
            self._log("异常: " + str(e)[:80])

    def shutdown(self):
        """优雅退出：保存配置、flush数据、停线程"""
        try:
            self._log("正在退出...")
            # 0. 先让后台线程进入退出状态 —— 否则下面保存数据时，
            #    `_bg_loop` / `_idle_worker` 还可能同时在写记忆/向量（互相打架），
            #    而且这几个 `while True` 线程以前根本停不下来（见 stop_background）。
            try:
                self.stop_background()
            except Exception as e:  # 静默是故意的 - 停不掉也要继续保存数据
                _x6_swallowed(__name__, e, "stop background")
            # 1. 保存配置
            try:
                self.save_config()
                self._log("配置已保存")
            except Exception as e:
                self._log("保存配置失败: %s" % str(e)[:60])
            
            # 2. 保存向量库
            try:
                vs = self.modules.get("vector_store")
                if vs and hasattr(vs, 'save'):
                    vs.save()
                    self._log("向量库已保存")
            except Exception as e:
                self._log("保存向量库失败: %s" % str(e)[:60])
            
            # 3. 保存记忆
            try:
                self.save_memory()
                self._log("记忆已保存")
            except Exception as e:
                self._log("保存记忆失败: %s" % str(e)[:60])

            # 4. 收掉 MCP 的 stdio 子进程 和 内嵌的本地工具服务
            #    npx / node 那些是用命令行起的，不收就会变成孤儿进程挂在后台。
            try:
                mc = self.modules.get("mcp_client")
                if mc and hasattr(mc, "stop"):
                    r = mc.stop()
                    self._log("MCP 子进程已收: %s" % (r or ""))
            except Exception as e:
                self._log("收 MCP 子进程失败: %s" % str(e)[:60])
            try:
                ms = self.modules.get("mcp_server")
                if ms and hasattr(ms, "stop_http"):
                    ms.stop_http()
                    self._log("本地工具服务已停")
            except Exception as e:
                self._log("停本地工具服务失败: %s" % str(e)[:60])

            # 5. 收 LLM 看门狗线程（`llm-watchdog` 原来是 while True 无出口）
            try:
                llm = self.modules.get("llm")
                if llm is not None and hasattr(llm, "stop"):
                    llm.stop()
                    self._log("LLM 看门狗已停")
            except Exception as e:
                self._log("停 LLM 看门狗失败: %s" % str(e)[:60])

            self._log("退出完成")
        except Exception as e:
            print("shutdown error:", e)
