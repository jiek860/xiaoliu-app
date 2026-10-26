# -*- coding: utf-8 -*-
"""所有后台 QThread worker 集中管理"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtCore import QThread, pyqtSignal
import os
import time
import uuid

from core.cancel_token import CancelToken


def _log_path(trunk):
    """活动对应的日志文件，供活动中心「查看日志」使用。"""
    try:
        base = getattr(trunk, "base", "") or os.getcwd()
        return os.path.join(base, "data", "logs", "app.log")
    except Exception:  # 静默是故意的
        return ""


def _reg_start(kind, title, log_path=""):
    try:
        from core.agent_harness import get_run_registry
        # 同一毫秒内启动同类 worker 时不能互相覆盖，所以补随机后缀
        rid = "%s:%d:%s" % (kind, int(time.time() * 1000),
                            uuid.uuid4().hex[:6])
        get_run_registry().start_run(
            kind, title, run_id=rid,
            metadata={"log_path": log_path} if log_path else None)
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
        # 取消令牌：不再是"只置个没人读的标志"，而是真正通知到流循环
        # 并 close 阻塞中的响应，让 Ollama 锁立刻释放。
        self._cancel = CancelToken()

    def stop(self):
        """用户按 Esc 打断回复：通知流循环并关闭网络连接"""
        self._cancel.cancel()

    def is_cancelled(self):
        return self._cancel.is_cancelled()

    def _guarded_token(self, text):
        """取消后不再往界面推 token（信号可能已断开，这里再兜一层）"""
        if not self._cancel.is_cancelled():
            self.token.emit(text)

    def run(self):
        rid = _reg_start("chat", "聊天回复：%s" % str(self.msg)[:40],
                         _log_path(self.trunk))
        try:
            self.trunk._log("[Worker] 开始处理: %s" % str(self.msg)[:30])
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        try:
            ans = self.trunk.reply(
                self.msg,
                on_token=self._guarded_token,
                force_chat=self.force_chat,
                cancel_token=self._cancel,
            )
            try:
                self.trunk._log("[Worker] 完成，长度 %d" % len(str(ans)))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            if self._cancel.is_cancelled():
                _reg_finish(rid, "cancelled")
                return
            _reg_finish(rid, "completed")
            self.done.emit(str(ans) if ans else "（无回复）")
        except BaseException as e:
            if self._cancel.is_cancelled():
                _reg_finish(rid, "cancelled")
                return
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
        rid = _reg_start("task_loop", "任务闭环：%s" % str(self.goal)[:40],
                         _log_path(self.trunk))
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
        rid = _reg_start("learning", "学习闭环", _log_path(self.trunk))
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
    """语音合成

    以前 `done` 声明了却从来没 emit —— SpeechController 把它接到播放器上，
    于是聊天里的"朗读回复"开关打开后**一直没声音**（用户以为坏了）。
    现在合成成功就把音频路径发回去，由 GUI 线程播放（可停、不会弹播放器）。
    """
    done = pyqtSignal(str)

    def __init__(self, trunk, text, autoplay=False):
        super().__init__()
        self.trunk = trunk
        self.text = text
        # autoplay=False：交给调用方的播放器播，避免和 os.startfile 双重播放
        self.autoplay = bool(autoplay)

    def run(self):
        rid = _reg_start("tts", "语音合成", _log_path(self.trunk))
        path = ""
        try:
            tts = self.trunk._load_lazy("tts")
            if tts:
                r = self._speak(tts)
                if isinstance(r, dict):
                    if r.get("ok") is False:
                        raise RuntimeError(str(r.get("error") or "语音合成失败"))
                    path = str(r.get("path") or "")
            _reg_finish(rid, "completed")
        except Exception as e:
            _reg_finish(rid, "failed", str(e)[:200])
            path = ""
        try:
            self.done.emit(path)
        except Exception as e:  # 静默是故意的 - 窗口已关闭时没人接收
            _x6_swallowed(__name__, e, "tts done signal")

    def _speak(self, tts):
        """兼容老插件签名 speak(text)：新签名多一个 autoplay 参数"""
        try:
            return tts.speak(self.text, autoplay=self.autoplay)
        except TypeError:
            return tts.speak(self.text)


class BgWorker(QThread):
    """通用后台：执行 fn，结果 emit"""
    done = pyqtSignal(object)

    def __init__(self, fn, title="后台操作", trunk=None):
        super().__init__()
        self.fn = fn
        self.title = title
        self.trunk = trunk

    def run(self):
        rid = _reg_start("background", str(self.title)[:50],
                         _log_path(self.trunk))
        try:
            r = self.fn()
            _reg_finish(rid, "completed")
            self.done.emit(r)
        except Exception as e:
            _reg_finish(rid, "failed", str(e)[:200])
            self.done.emit(f"错误: {str(e)[:120]}")

