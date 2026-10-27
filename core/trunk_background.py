# -*- coding: utf-8 -*-
"""Trunk 启动预热、备份、后台队列和资源回收。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TrunkBackgroundMixin:
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
            time.sleep(2)
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
        """P2-4: 延迟3秒启动后台服务，不阻塞UI"""
        time.sleep(3)
        try:
            from core.lazy_health import compile_lazy_sources
            _lh = compile_lazy_sources(self.base)
            if not _lh.get("ok"):
                self._log("懒加载语法自检失败: %s" % str(
                    _lh.get("errors", [])[:3])[:300])
            else:
                self._log("懒加载语法自检通过: %d 个模块" % _lh.get("checked", 0))
        except Exception as e:
            self._log("懒加载语法自检异常: " + str(e)[:120])
        # 定时任务（内部会启动连续学习线程）
        try:
            self.call("scheduler", "start")
            self._log("定时任务已启动")
        except Exception as e:
            self._log("定时任务启动失败: %s" % str(e)[:60])
        # 热更新检测（每5分钟自动扫 .py 变化）
        try:
            hr = self._load_lazy("hot_reload")
            if hr and hasattr(hr, "auto_reload"):
                hr.auto_reload()
                self._log("热更新已启动")
        except Exception as e:
            self._log("热更新启动失败: %s" % str(e)[:60])
        # 模块服务器（本机插件仓库，127.0.0.1:8899）
        # 配置成远程地址时只连远程、不拉起本地服务（见 部署步骤.md 第五节）
        try:
            cfg_url = str(self.config.get("module_server", "") or "")
            if (not cfg_url) or ("127.0.0.1" in cfg_url) or ("localhost" in cfg_url):
                from core.module_server import ModuleServer
                if getattr(self, "_module_server", None) is None:
                    self._module_server = ModuleServer(self)
                    self._log(str(self._module_server.start())[:70])
            else:
                self._log("模块服务器: 配置为远程地址 %s，不拉起本地服务" % cfg_url[:40])
        except Exception as e:
            self._log("模块服务器启动失败: %s" % str(e)[:60])
        # MCP 服务端 + 客户端
        # 服务端是内嵌的本地工具服务：把 chat / search / run_code / backup
        # 包成 HTTP 接口（127.0.0.1:3742），供客户端那条「本地工具」配置连。
        # 原来这里只调了 ms.run()（返回工具清单，什么也不启动），
        # start_http() 全项目没有调用点，所以那个服务从来没起来过。
        try:
            ms = self._load_lazy("mcp_server")
            if ms and hasattr(ms, "start_http"):
                self._log("本地工具服务: %s" % str(ms.start_http())[:80])
        except Exception as e:
            self._log("本地工具服务启动失败: %s" % str(e)[:60])
        try:
            mc = self._load_lazy("mcp_client")
            if mc:
                r = mc.run()
                self._log("MCP客户端: %d个工具" % r.get("可用工具数", r.get("工具数", 0)))
        except Exception as e:
            self._log("MCP客户端: %s" % str(e)[:40])
        # Ollama 后台预热
        threading.Thread(target=self._warmup_ollama, daemon=True).start()
        # 定期内存清理：memory_optimizer 登记了很久没人调用
        # （它只做 gc.collect() + 收窄内部历史缓存，不动任何数据，放后台安全）
        try:
            self.call("memory_optimizer", "__no__")
            mo = self.modules.get("memory_optimizer")
            if mo is not None and hasattr(mo, "start_periodic"):
                r = mo.start_periodic(1800)
                self._log("内存优化: %s" % str(r.get("状态", "已启动")))
        except Exception as e:
            self._log("内存优化启动失败: %s" % str(e)[:60])

    _AUTO_BACKUP_MIN_GAP_H = 6

    def _auto_backup(self):
        """启动时自动备份一次 —— 走真正的备份系统（core/backup.py）

        和历史的关系
        ------------
        原来这里是自己拷几个关键文件到 data/backup_MMDD_HHMM、留最近 2 份。
        但项目里本来就有 core/backup.py：增量、排除 datasets/cache/logs、
        写 backups/、还支持加密导出和恢复。两套并存的问题不只是重复：
          · 产物分散在两个地方（data/backup_* 和 backups/backup_*），
            要恢复时不知道该看哪个
          · 自检的"📦 备份"数的是旧的 data/backup_*，真正的 backups/ 反而没数
          · 旧那套的排除规则是手写的文件清单，容易和实际存储漂移
            （历史上就漏备过 memory.json / graph.json / chats.db）
        现在融合成一条：启动时触发真正的备份，产物统一进 backups/。

        另加节流：距上次备份不足 _AUTO_BACKUP_MIN_GAP_H 小时就跳过。

        节流做两层（2026-10-27）：
          ① 这里先快速看一眼最近一份（省掉建 Backup 的开销）
          ② 真正的判断在 Backup.backup_now(force=False, min_gap_h=...) 的**锁内** ——
             两个线程同时进来时，第二个能看到第一个刚落盘的备份，
             不会再出现同一秒两份（backup_..._211951 / _211951_2）。
        测试/CI 里设环境变量 X6_NO_AUTO_BACKUP=1 可直接关掉（它会写真实磁盘）。
        """
        # 测试/CI 短路：conftest 默认设了，单测里造 Trunk 不会写真实备份
        if str(os.environ.get("X6_NO_AUTO_BACKUP", "")).strip().lower() \
                not in ("", "0", "false", "no"):
            return
        try:
            from core.backup import Backup
            bk = Backup(self)
            last = bk._last_backup_path()
            if last and self._backup_is_recent(last):
                return
            r = bk.backup_now(force=False,
                              min_gap_h=self._AUTO_BACKUP_MIN_GAP_H) or {}
            if r.get("跳过"):
                return
            if r.get("成功"):
                self._log("启动备份完成: %s（%s）"
                          % (r.get("备份到"), "增量" if r.get("增量") else "全量"))
            else:
                self._log("启动备份未完成: %s" % str(r.get("错误"))[:60])
        except Exception as e:
            self._log("启动备份失败: %s" % str(e)[:60])

    def _backup_is_recent(self, path):
        """最近的备份是否还在节流窗口内"""
        import time as _t
        try:
            age_h = (_t.time() - os.path.getmtime(path)) / 3600.0
            return age_h < self._AUTO_BACKUP_MIN_GAP_H
        except Exception:
            return False

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
        import time as _t, gc
        # 常驻白名单：核心 + 后台服务（定时任务/热更新/学习闭环等带独立线程的模块不可卸载，
        # 否则 stop() 会停掉服务线程。
        core = {"llm", "vector_store", "auth", "backup", "knowledge_graph",
                "rules_engine",
                "scheduler", "hot_reload", "error_lib",
                "learning_loop", "memory_loop"}
        while True:
            _t.sleep(30)
            try:
                now = _t.time()
                to_unload = []
                for name in list(self.modules.keys()):
                    if name in core:
                        continue
                    last = self._last_use.get(name, 0)
                    if last and now - last > 300:  # P0-1: 5分钟才卸载，避免反复懒加载拖慢
                        to_unload.append(name)
                for name in to_unload:
                    try:
                        mod = self.modules.get(name)
                        for m in ["stop", "close", "shutdown", "cleanup"]:
                            fn = getattr(mod, m, None)
                            if fn:
                                try:
                                    fn()
                                except Exception as e:
                                    self._log("异常: " + str(e)[:80])
                        del self.modules[name]
                        if name in self._lazy:
                            mod_path = "core." + self._lazy[name][0]
                            if mod_path in sys.modules:
                                try:
                                    del sys.modules[mod_path]
                                except Exception as e:
                                    self._log("异常: " + str(e)[:80])
                        gc.collect()
                        self._log("真卸载模块: %s" % name)
                    except Exception as e:
                        self._log("卸载%s失败: %s" % (name, str(e)[:50]))
            except Exception as e:
                self._log("自动卸载线程出错: %s" % str(e)[:50])

    def _bg_loop(self):
        """P0-4: 后台任务单线程工作循环"""
        while True:
            run_id = ""
            try:
                task = self._bg_queue.get()
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
        while True:
            try:
                task = self._idle_queue.get()
                if task is None:
                    break
                # 最多等 10 分钟；等不到就放弃这一轮，避免无限积压
                deadline = time.time() + 600
                while self._chat_busy() and time.time() < deadline:
                    time.sleep(5)
                if self._chat_busy():
                    # 一直没等到空闲：这轮反思/记忆沉淀就没了，得让用户知道
                    self._warn_user("你聊得太连续，后台整理这轮跳过了")
                    continue
                try:
                    task()
                except Exception as e:
                    self._warn_user("后台整理出错（详情见日志）", e)
                time.sleep(1)          # 任务之间喘口气，别一口气把模型打满
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

            self._log("退出完成")
        except Exception as e:
            print("shutdown error:", e)
