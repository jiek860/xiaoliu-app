# -*- coding: utf-8 -*-
"""语音混入：语音输入按钮"""
import threading
from PyQt5.QtWidgets import QMessageBox, QApplication


class VoiceMixin:
    """语音相关方法"""
    def _voice_btn_clicked(self):
        if getattr(self, "_voice_recording", False):
            return
        self._voice_recording = True
        self.voice_btn.setText("录音中")
        self.voice_btn.setEnabled(False)
        QApplication.processEvents()
        def _do_listen():
            try:
                r = self.speech.listen_once(5)
                text = (r.get("文字") or "").strip()
                # 回到主线程更新UI
                self.input.setPlainText(self.input.toPlainText() + text)
                self.input.setFocus()
                if not text:
                    QMessageBox.information(self, "语音", "没听清: " + r.get("错误", "再试一次"))
            except Exception as e:
                QMessageBox.warning(self, "语音", "录音失败: " + str(e)[:80])
            finally:
                self.voice_btn.setText("语音输入")
                self.voice_btn.setEnabled(True)
                self._voice_recording = False
        threading.Thread(target=_do_listen, daemon=True).start()
