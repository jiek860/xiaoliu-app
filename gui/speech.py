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
        self._workers = []           # 只保住引用：QThread 被 GC 会带着播放一起没了

    def play(self, path, on_error=None):
        """播放合成好的音频；失败返回 False，并把原因交给 ``on_error``。"""
        if not path or not os.path.exists(path):
            self._report(on_error, "没有拿到音频文件（语音合成可能失败了）")
            return False
        try:
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
            from PyQt5.QtCore import QUrl
        # 静默是故意的 - 没 QtMultimedia 就退回系统播放器，至少能出声
        except Exception as e:
            _x6_swallowed(__name__, e, "import QtMultimedia")
            return self._startfile(path, on_error)
        try:
            if self._audio_player is None:
                self._audio_player = QMediaPlayer(self.parent)
            self._audio_player.stop()
            self._audio_player.setMedia(
                QMediaContent(QUrl.fromLocalFile(os.path.abspath(path)))
            )
            self._audio_player.play()
            return True
        # 静默是故意的 - 播放器起不来时退回系统播放器，不让用户"点了没反应"
        except Exception as e:
            _x6_swallowed(__name__, e, "play tts audio")
            return self._startfile(path, on_error)

    def _startfile(self, path, on_error=None):
        """兜底播放：用系统默认播放器打开（可能弹窗，但至少有声音）。"""
        try:
            os.startfile(os.path.abspath(path))     # noqa: S606 - 只播自己合成的音频
            return True
        # 静默是故意的 - 兜底也失败就必须告诉用户为什么没声音
        except Exception as e:
            _x6_swallowed(__name__, e, "startfile tts audio")
            self._report(on_error, "播放失败：%s" % str(e)[:80])
            return False

    @staticmethod
    def _report(on_error, message):
        if callable(on_error):
            try:
                on_error(str(message))
            except Exception as e:  # 静默是故意的 - 提示失败不能再抛一次
                _x6_swallowed(__name__, e, "tts error callback")

    def speak_async(self, text, on_error=None):
        """后台合成 → 回到 GUI 线程播放；失败把原因回调出去。"""
        from gui.workers import TTSWorker
        worker = TTSWorker(self.trunk, text)
        worker.done.connect(lambda p: self.play(p, on_error))
        if callable(on_error):
            worker.failed.connect(on_error)
        worker.finished.connect(lambda: self._forget(worker))
        self._workers.append(worker)
        self._tts_worker = worker
        worker.start()
        return worker

    def _forget(self, worker):
        try:
            self._workers.remove(worker)
        except ValueError as e:  # 静默是故意的 - 已经移除过就算了
            _x6_swallowed(__name__, e, "forget tts worker")

    def listen_once(self, seconds: int = 5, stop_event=None, on_partial=None):
        """录一次音并返回 {文字, 错误}。

        返回键必须归一化：Voice.listen() 给的是 {ok, text, error}，
        而调用方（voice_mixin / 语音对话）读的是 文字/错误。
        以前直接把原始 dict 透传，两边键名对不上 —— 识别成功也永远读成空，
        于是每次录音都提示"没听清: 再试一次"。

        ``stop_event``：按住说话松开时由 GUI set；老模块没有这个参数，
        TypeError 时退回固定时长，保证旧插件也能用。
        ``on_partial``：流式中间结果回调；模块不支持时自动降级为不流式。
        """
        v = self.trunk.modules.get("voice") or self.trunk._load_lazy("voice")
        if not v:
            return {"文字": "", "错误":
                    "语音模块没加载起来。到「设置 → 扩展 → 功能扩展组件」里"
                    "装上「语音识别」，或检查 optional_libs 里的 faster-whisper"}
        try:
            if on_partial is not None:
                try:
                    r = v.listen(seconds, stop_event=stop_event,
                                 on_partial=on_partial)
                except TypeError:
                    # 老模块不认 on_partial：退回不流式
                    try:
                        r = v.listen(seconds, stop_event=stop_event)
                    except TypeError:
                        r = v.listen(seconds)
            elif stop_event is not None:
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


