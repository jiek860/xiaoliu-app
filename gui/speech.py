# -*- coding: utf-8 -*-
"""语音：内置播放 + 录音输入"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os


class SpeechController:
    def __init__(self, trunk, parent_widget):
        self.trunk = trunk
        self.parent = parent_widget
        self._audio_player = None
        self._tts_worker = None

    def play(self, path):
        try:
            if not path or not os.path.exists(path):
                return
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
            from PyQt5.QtCore import QUrl
            if self._audio_player is None:
                self._audio_player = QMediaPlayer(self.parent)
            self._audio_player.stop()
            self._audio_player.setMedia(
                QMediaContent(QUrl.fromLocalFile(os.path.abspath(path)))
            )
            self._audio_player.play()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def speak_async(self, text):
        from gui.workers import TTSWorker
        self._tts_worker = TTSWorker(self.trunk, text)
        self._tts_worker.done.connect(self.play)
        self._tts_worker.start()

    def listen_once(self, seconds: int = 5):
        v = self.trunk.modules.get("voice") or self.trunk._load_lazy("voice")
        if not v:
            return {"文字": "", "错误": "语音模块加载失败"}
        return v.listen(seconds)

