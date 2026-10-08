# -*- coding: utf-8 -*-
"""所有后台 QThread worker 集中管理"""
from PyQt5.QtCore import QThread, pyqtSignal


class StreamWorker(QThread):
    """聊天流式回复"""
    token = pyqtSignal(str)
    done = pyqtSignal(str)

    def __init__(self, trunk, msg):
        super().__init__()
        self.trunk = trunk
        self.msg = msg
        self._is_stopped = False
    def stop(self):
        """用户按Esc打断回复"""
        self._is_stopped = True

    def run(self):
        try:
            self.trunk._log("[Worker] 开始处理: %s" % str(self.msg)[:30])
        except Exception:
            pass
        try:
            ans = self.trunk.reply(
                self.msg,
                on_token=lambda t: self.token.emit(t),
            )
            try:
                self.trunk._log("[Worker] 完成，长度 %d" % len(str(ans)))
            except Exception:
                pass
            self.done.emit(str(ans) if ans else "（无回复）")
        except BaseException as e:
            import traceback
            tb = traceback.format_exc()[-500:]
            try:
                self.trunk._log("[Worker] 崩溃: " + tb)
            except Exception:
                pass
            try:
                self.trunk.call("error_lib", "log",
                                "reply", "reply", str(e)[:200])
            except Exception:
                pass
            try:
                self.done.emit("抱歉，回复时出了点问题，详情已记入日志")
            except Exception:
                pass


class TaskWorker(QThread):
    """任务闭环"""
    done = pyqtSignal(dict)

    def __init__(self, trunk, goal):
        super().__init__()
        self.trunk = trunk
        self.goal = goal

    def run(self):
        try:
            tl = self.trunk.modules.get("task_loop")
            if not tl:
                self.trunk.call("task_loop", "__no__")
                tl = self.trunk.modules.get("task_loop")
            if not tl:
                self.done.emit({"ok": False, "原因": "task_loop 加载失败"})
                return
            self.done.emit(tl.run(self.goal))
        except Exception as e:
            self.done.emit({"ok": False, "原因": str(e)[:100]})


class LearnWorker(QThread):
    """学习闭环"""
    done = pyqtSignal(dict)

    def __init__(self, trunk):
        super().__init__()
        self.trunk = trunk

    def run(self):
        try:
            ll = self.trunk.modules.get("learning_loop")
            if not ll:
                self.trunk.call("learning_loop", "__no__")
                ll = self.trunk.modules.get("learning_loop")
            if not ll:
                self.done.emit({"ok": False, "原因": "learning_loop 加载失败"})
                return
            self.done.emit(ll.run())
        except Exception as e:
            self.done.emit({"ok": False, "原因": str(e)[:100]})


class TTSWorker(QThread):
    """语音合成"""
    done = pyqtSignal(str)

    def __init__(self, trunk, text):
        super().__init__()
        self.trunk = trunk
        self.text = text

    def run(self):
        try:
            tts = self.trunk._load_lazy("tts")
            if tts:
                tts.speak(self.text)
        except Exception:
            pass


class BgWorker(QThread):
    """通用后台：执行 fn，结果 emit"""
    done = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.done.emit(f"错误: {str(e)[:120]}")

