# -*- coding: utf-8 -*-
"""所有后台 QThread worker 集中管理"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtCore import QThread, pyqtSignal
import time


def _reg_start(kind, title):
    try:
        from core.agent_harness import get_run_registry
        rid = "%s:%s" % (kind, int(time.time() * 1000))
        get_run_registry().start_run(kind, title, run_id=rid)
        return rid
    except Exception:  # 静默是故意的
        return ""


def _reg_finish(run_id, status="completed", error=""):
    if not run_id:
        return
    try:
        from core.agent_harness import get_run_registry
        get_run_registry().finish_run(run_id, status, error)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "best-effort fallback")


class StreamWorker(QThread):
    """聊天流式回复"""
    token = pyqtSignal(str)
    done = pyqtSignal(str)

    def __init__(self, trunk, msg, force_chat=False):
        super().__init__()
        self.trunk = trunk
        self.msg = msg
        self.force_chat = bool(force_chat)
        self._is_stopped = False
    def stop(self):
        """用户按Esc打断回复"""
        self._is_stopped = True

    def run(self):
        rid = _reg_start("chat", "聊天回复：%s" % str(self.msg)[:40])
        try:
            self.trunk._log("[Worker] 开始处理: %s" % str(self.msg)[:30])
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        try:
            ans = self.trunk.reply(
                self.msg,
                on_token=lambda t: self.token.emit(t),
                force_chat=self.force_chat,
            )
            try:
                self.trunk._log("[Worker] 完成，长度 %d" % len(str(ans)))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            _reg_finish(rid, "completed")
            self.done.emit(str(ans) if ans else "（无回复）")
        except BaseException as e:
            _reg_finish(rid, "failed", str(e)[:300])
            import traceback
            tb = traceback.format_exc()[-500:]
            try:
                self.trunk._log("[Worker] 崩溃: " + tb)
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            try:
                self.trunk.call("error_lib", "log",
                                "reply", "reply", str(e)[:200])
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            try:
                self.done.emit("抱歉，回复时出了点问题，详情已记入日志")
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass


class TaskWorker(QThread):
    """任务闭环"""
    done = pyqtSignal(dict)

    def __init__(self, trunk, goal):
        super().__init__()
        self.trunk = trunk
        self.goal = goal

    def run(self):
        rid = _reg_start("task_loop", "任务闭环：%s" % str(self.goal)[:40])
        try:
            tl = self.trunk.modules.get("task_loop")
            if not tl:
                self.trunk.call("task_loop", "__no__")
                tl = self.trunk.modules.get("task_loop")
            if not tl:
                _reg_finish(rid, "failed", "task_loop 加载失败")
                self.done.emit({"ok": False, "原因": "task_loop 加载失败"})
                return
            r = tl.run(self.goal)
            _reg_finish(rid, "completed" if (isinstance(r, dict) and r.get("ok", True)) else "failed",
                        str(r.get("原因", "")) if isinstance(r, dict) else "")
            self.done.emit(r)
        except Exception as e:
            _reg_finish(rid, "failed", str(e)[:200])
            self.done.emit({"ok": False, "原因": str(e)[:100]})


class LearnWorker(QThread):
    """学习闭环"""
    done = pyqtSignal(dict)

    def __init__(self, trunk):
        super().__init__()
        self.trunk = trunk

    def run(self):
        rid = _reg_start("learning", "学习闭环")
        try:
            ll = self.trunk.modules.get("learning_loop")
            if not ll:
                self.trunk.call("learning_loop", "__no__")
                ll = self.trunk.modules.get("learning_loop")
            if not ll:
                _reg_finish(rid, "failed", "learning_loop 加载失败")
                self.done.emit({"ok": False, "原因": "learning_loop 加载失败"})
                return
            r = ll.run()
            _reg_finish(rid, "completed" if (isinstance(r, dict) and r.get("ok", True)) else "failed")
            self.done.emit(r)
        except Exception as e:
            _reg_finish(rid, "failed", str(e)[:200])
            self.done.emit({"ok": False, "原因": str(e)[:100]})


class TTSWorker(QThread):
    """语音合成"""
    done = pyqtSignal(str)

    def __init__(self, trunk, text):
        super().__init__()
        self.trunk = trunk
        self.text = text

    def run(self):
        rid = _reg_start("tts", "语音合成")
        try:
            tts = self.trunk._load_lazy("tts")
            if tts:
                tts.speak(self.text)
            _reg_finish(rid, "completed")
        except Exception:  # 静默是故意的
            _reg_finish(rid, "failed")


class BgWorker(QThread):
    """通用后台：执行 fn，结果 emit"""
    done = pyqtSignal(object)

    def __init__(self, fn, title="后台操作"):
        super().__init__()
        self.fn = fn
        self.title = title

    def run(self):
        rid = _reg_start("background", str(self.title)[:50])
        try:
            r = self.fn()
            _reg_finish(rid, "completed")
            self.done.emit(r)
        except Exception as e:
            _reg_finish(rid, "failed", str(e)[:200])
            self.done.emit(f"错误: {str(e)[:120]}")

