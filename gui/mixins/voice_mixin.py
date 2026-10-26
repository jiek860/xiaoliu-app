# -*- coding: utf-8 -*-
"""语音混入：语音输入按钮

线程安全说明
------------
原来 _do_listen 跑在 threading.Thread 里，却直接操作控件：
    self.input.setPlainText(self.input.toPlainText() + text)
    self.input.setFocus()
    QMessageBox.information(...)
    self.voice_btn.setText(...) / setEnabled(...)
注释里写着"回到主线程更新UI"，但**根本没有回主线程** ——
Qt 规定控件只能在 GUI 线程碰，这么做会随机崩
（和之前 model_manager_dialog 在子线程里 list_w.clear() 是同一类问题）。

现在走 _VoiceRelay：子线程只 emit 信号，Qt 会把它排队到接收者所在的线程，
槽函数 _on_voice_done 因此在 GUI 线程里执行，碰控件是安全的。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import threading

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QApplication


class _VoiceRelay(QObject):
    """把子线程的识别结果送回 GUI 线程（跨线程 emit 信号是安全的）"""
    done = pyqtSignal(str, str)          # (识别出的文字, 错误信息)


class VoiceMixin:
    """语音相关方法"""

    def _voice_btn_clicked(self):
        if getattr(self, "_voice_recording", False):
            return
        speech = getattr(self, "speech", None)
        if speech is None:
            QMessageBox.information(self, "语音", "语音组件没初始化，重启程序再试")
            return
        self._voice_recording = True
        self.voice_btn.setText("录音中")
        self.voice_btn.setEnabled(False)
        QApplication.processEvents()

        # 中继对象以窗口为父、并把引用挂到 self 上 ——
        # 只写成局部变量的话，函数返回后它可能被 Python 回收，
        # 后台线程 emit 的信号就没人接了（settings_dialog 里踩过这个坑）。
        relay = getattr(self, "_voice_relay", None)
        if relay is None:
            relay = _VoiceRelay(self)
            relay.done.connect(self._on_voice_done)
            self._voice_relay = relay

        def _do_listen():
            """子线程：只做识别，**不碰任何控件**"""
            text, err = "", ""
            try:
                r = speech.listen_once(5)
                text = (r.get("文字") or "").strip()
                if not text:
                    err = str(r.get("错误") or "没听清，再说一遍试试")
            except Exception as e:
                err = "录音失败: " + str(e)[:80]
            relay.done.emit(text, err)       # 排队回 GUI 线程

        threading.Thread(target=_do_listen, daemon=True).start()

    def _on_voice_done(self, text, err):
        """在 GUI 线程里收尾（信号槽默认排队到接收者所在线程）"""
        try:
            if text:
                cur = self.input.toPlainText()
                # 与已有文字之间留一个空格，否则两句会粘在一起
                if cur and not cur.endswith((" ", "\n", "\t")):
                    cur += " "
                self.input.setPlainText(cur + text)
                self.input.setFocus()
            elif err:
                QMessageBox.information(self, "语音", _voice_error_text(err))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        finally:
            self.voice_btn.setText("语音输入")
            self.voice_btn.setEnabled(True)
            self._voice_recording = False


def _voice_error_text(err):
    """把"缺少 pyaudio"这类原始报错换成能照着做的提示"""
    raw = str(err or "").strip()
    if "pyaudio" in raw.lower():
        try:
            from core.error_text import install_hint
            return "麦克风要用的 pyaudio 还没装。\n\n" + install_hint("pyaudio")
        except Exception as e:  # 静默是故意的 - 提示失败就退回原始文本
            _x6_swallowed(__name__, e, "voice install hint")
    return raw
