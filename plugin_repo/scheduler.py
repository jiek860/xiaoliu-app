# -*- coding: utf-8 -*-
"""定时调度 v10.0 - 真24小时后台：定时备份+主动学习+巡检+热更新检测"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from core.safe_http import open_url as safe_open_url
from modules.base import BaseModule
import threading, time

class Scheduler(BaseModule):
    NAME = "scheduler"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.running = False
        self.thread = None
        self.last_backup = 0
        self.last_check = 0
        self.last_heal = 0
        self.last_review = 0
        self._learn_started = False
        self.last_learn = 0  # D7: 修复 status() 引用未定义属性
        self.last_health = 0  # P2-9: 模型健康巡检
        self.last_auto = 0  # 自动更新巡检（P0-3: 每6小时检查建议，部署需手动确认）
        self.last_anomaly = 0  # 异常检测（接上 anomaly_detector，只读检查）
        self._boot_time = time.time()  # v10.1: 启动先让用户用聊天，后台闭环延后开跑，不抢 Ollama
        self.last_error = ""  # D7: 最近一次任务失败信息
        self.fail_count = 0

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def _safe_run(self, name, fn):
        """D7: 任务失败自动重试 1 次 + 写错误库告警 + 记录最近错误"""
        try:
            fn()
            return True
        except Exception as e:
            self.fail_count += 1
            msg = "%s失败: %s" % (name, str(e)[:120])
            self.last_error = msg
            try:  # 重试 1 次
                fn()
                return True
            except Exception as e2:
                self.fail_count += 1
                self.last_error = "%s重试仍失败: %s" % (name, str(e2)[:120])
                try:
                    el = self.trunk.modules.get("error_lib")
                    if el:
                        el.log("scheduler", name, self.last_error)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
                return False

    def _loop(self):
        while self.running:
            now = time.time()
            busy = self.trunk._chat_busy() if hasattr(self.trunk, "_chat_busy") else False
            try:
                bk_iv = self.trunk.rule("定时.备份间隔秒", 3600)
                heal_iv = self.trunk.rule("定时.错误库维护间隔秒", 14400)
                rv_iv = self.trunk.rule("定时.复习间隔秒", 1800)
                rc_iv = self.trunk.rule("定时.热检间隔秒", 300)
                auto_iv = self.trunk.rule("定时.自动更新间隔秒", 21600)
                an_iv = self.trunk.rule("定时.异常检测间隔秒", 3600)
            except Exception:
                bk_iv, heal_iv, rv_iv, rc_iv, auto_iv, an_iv = 3600, 14400, 1800, 300, 21600, 3600
            # 每小时备份（D7: 失败自动重试+告警）
            if now - self.last_backup > bk_iv:
                def _do_backup():
                    bk = self.trunk.modules.get("backup")
                    if bk and hasattr(bk, "backup_now"):
                        bk.backup_now()
                self._safe_run("备份", _do_backup)
                self.last_backup = now
            # 连续自主学习：启动 120 秒后才开第一轮（先保证聊天能用，不抢模型）
            if not self._learn_started and now - self._boot_time > 120:
                def _start_learn():
                    self.trunk.call("learning_loop", "__no__")
                    ll = self.trunk.modules.get("learning_loop")
                    if ll and hasattr(ll, "start_continuous"):
                        ll.start_continuous(1200)
                    self._learn_started = True
                self._safe_run("主动学习", _start_learn)
            # 每4小时错误库例行维护（启动 300 秒后首轮；聊天中让路）
            #
            # 原来这里是"自愈闭环"：调 self_heal.run()。但那个模块名字叫自愈、
            # 实际只把错误记录标成已处理、不改任何代码，LLM 生成的那段建议
            # 也只是被当成文字存下来。已删除。
            # 保留它真正做过的唯一有用的事 —— 标记 + 清理，直接由错误库自己做。
            if busy:
                pass
            elif now - self.last_heal > heal_iv and now - self._boot_time > 300:
                def _tidy_errors():
                    el = self.trunk.modules.get("error_lib")
                    if not el:
                        self.trunk.call("error_lib", "__no__")
                        el = self.trunk.modules.get("error_lib")
                    if el and hasattr(el, "mark_all_fixed"):
                        el.mark_all_fixed()
                        if hasattr(el, "cleanup_fixed"):
                            el.cleanup_fixed(72)      # 已处理的留 3 天
                self._safe_run("错误库维护", _tidy_errors)
                self.last_heal = now
            # 每6小时自动更新巡检（启动600秒后首轮；只检查+生成建议，部署需弹窗确认）
            if now - self.last_auto > auto_iv and now - self._boot_time > 600:
                def _auto():
                    self.trunk.call("auto_updater", "__no__")
                    au = self.trunk.modules.get("auto_updater")
                    if au and hasattr(au, "collect_problems"):
                        probs = au.collect_problems()
                        if probs:
                            self.trunk._log("自动更新巡检: 发现 %d 项待办（部署需手动确认）" % len(probs))
                self._safe_run("自动更新巡检", _auto)
                self.last_auto = now
            # 每1小时异常检测（启动 300 秒后首轮）
            # anomaly_detector 登记了很久但一直没人调用它 —— 它就是做监控的。
            # 只读检查（check_health 不改任何数据），放后台跑是安全的。
            if now - self.last_anomaly > an_iv and now - self._boot_time > 300:
                def _anomaly():
                    self.trunk.call("anomaly_detector", "__no__")
                    ad = self.trunk.modules.get("anomaly_detector")
                    if ad and hasattr(ad, "check_health"):
                        r = ad.check_health() or {}
                        warn = r.get("告警") or r.get("warnings") or []
                        if warn:
                            self.trunk._log("异常检测: %s" % str(warn)[:120])
                self._safe_run("异常检测", _anomaly)
                self.last_anomaly = now
            # 每30分钟记忆复习（启动 300 秒后首轮）
            # 加 not busy：复习会走 vector_store.add → 嵌入请求（Ollama），
            # 是这批定时任务里唯一会跟聊天抢模型的，所以聊天中让路。
            # 其余任务（备份/热检/异常检测/健康自检）是磁盘或轻 HTTP 操作，不必让。
            if now - self.last_review > rv_iv and now - self._boot_time > 300 and not busy:
                def _review():
                    self.trunk.call("memory_loop", "__no__")
                    ml = self.trunk.modules.get("memory_loop")
                    if ml and hasattr(ml, "do_review"):
                        ml.do_review()
                self._safe_run("记忆复习", _review)
                self.last_review = now
            if now - self.last_health > 600 and now - self._boot_time > 120:
                def _health():
                    # ① Ollama 可达性 + 模型数（用配置地址，非硬编码）
                    try:
                        import urllib.request
                        import json as _j
                        _u = self.trunk.config.get("ollama_url", "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
                        r = safe_open_url(_u, timeout=5)
                        d = _j.loads(r.read().decode("utf-8", "ignore"))
                        self.trunk._log("巡检: Ollama正常, 本地模型%d个" % len(d.get("models", [])))
                    except Exception as e:
                        self.trunk._log("巡检: Ollama不可达: %s" % str(e)[:60])
                        try:
                            el = self.trunk.modules.get("error_lib")
                            if el:
                                el.log("scheduler", "health", "Ollama不可达: " + str(e)[:80])
                        except Exception as e:
                            _x6_swallowed(__name__, e)
                            pass
                self._safe_run("模型巡检", _health)
                self.last_health = now
            # 每5分钟热更新检测
            if now - self.last_check > rc_iv:
                def _reload():
                    self.trunk.call("hot_reload", "__no__")
                    hr = self.trunk.modules.get("hot_reload")
                    if hr and hasattr(hr, "check_changes"):
                        changes = hr.check_changes()
                        for c in changes:
                            ok, msg = hr.reload_module(c)
                            if not ok:
                                # 失败标记 → GUI 轮询弹窗提示
                                self.trunk._last_hr_fail = {"time": time.strftime("%H:%M:%S"), "模块": msg}
                                self.trunk._log("热更新失败: " + str(msg)[:120])
                self._safe_run("热更新检测", _reload)
                self.last_check = now
            time.sleep(60)  # 每分钟检查一次

    def status(self):
        return {"运行中": self.running, "上次备份": self.last_backup,
                "上次学习": self.last_learn, "失败次数": self.fail_count,
                "最近错误": self.last_error}

    def run(self, *args):
        return self.status()
