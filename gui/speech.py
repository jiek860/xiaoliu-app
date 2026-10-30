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

    def listen_once(self, seconds: int = 5, stop_event=None):
        """录一次音并返回 {文字, 错误}。

        返回键必须归一化：Voice.listen() 给的是 {ok, text, error}，
        而调用方（voice_mixin / 语音对话）读的是 文字/错误。
        以前直接把原始 dict 透传，两边键名对不上 —— 识别成功也永远读成空，
        于是每次录音都提示"没听清: 再试一次"。

        ``stop_event``：按住说话松开时由 GUI set；老模块没有这个参数，
        TypeError 时退回固定时长，保证旧插件也能用。
        """
        v = self.trunk.modules.get("voice") or self.trunk._load_lazy("voice")
        if not v:
            return {"文字": "", "错误":
                    "语音模块没加载起来。到「设置 → 扩展 → 功能扩展组件」里"
                    "装上「语音识别」，或检查 optional_libs 里的 faster-whisper"}
        try:
            if stop_event is not None:
                try:
                    r = v.listen(seconds, stop_event=stop_event)
                except TypeError:
                    r = v.listen(seconds)
            else:
                r = v.listen(seconds)
        except Exception as e:
            return {"文字": "", "错误": "录音失败: " + str(e)[:80]}
        if not isinstance(r, dict):
            return {"文字": "", "错误": "语音模块返回格式不对"}
        if r.get("ok") is False:
            return {"文字": "", "错误": str(r.get("error") or "识别失败")[:120]}
        text = str(r.get("text") or r.get("文字") or "").strip()
        return {"文字": text, "错误": "" if text else "没听清，再说一遍试试"}


