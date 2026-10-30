# -*- coding: utf-8 -*-
"""语音模块：缺依赖、坏路径和成功转写路径。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from modules.installed.voice import Voice, _detect_backend  # noqa: E402


class _FakeTrunk:
    base = BASE
    config = {"asr_idle_unload_sec": 0}


class _Backend:
    def transcribe(self, audio, **kw):
        return {"text": "hello", "segments": [], "language": "en",
                "duration": 0.5}


def _voice():
    return Voice(_FakeTrunk())


def test_voice_rejects_bad_input_and_missing_file(tmp_path):
    v = _voice()
    assert v.transcribe(["not-a-path"])["ok"] is False
    assert v.transcribe(str(tmp_path / "missing.wav"))["ok"] is False


def test_voice_load_backend_error_is_friendly(monkeypatch):
    v = _voice()
    monkeypatch.setattr("modules.installed.voice._detect_backend",
                        lambda: None)
    r = v.transcribe(__file__)
    assert r["ok"] is False
    assert "语音识别后端" in r["error"]


def test_voice_transcribe_success_updates_stats(monkeypatch):
    v = _voice()
    monkeypatch.setattr(v, "_load_backend", lambda: _Backend())
    v._backend_kind = "faster-whisper"
    r = v.transcribe(__file__)
    assert r == {"ok": True, "text": "hello"}
    assert v.stats()["语音识别次数"] == 1


def test_voice_listen_without_pyaudio_is_friendly(monkeypatch):
    v = _voice()
    monkeypatch.setitem(sys.modules, "pyaudio", None)
    r = v.listen(seconds=0.01)
    assert r["ok"] is False
    assert "pyaudio" in r["error"]


def test_detect_backend_returns_known_value_or_none():
    assert _detect_backend() in (None, "faster-whisper", "openai-whisper")


# ──────────────────────────────────────────────────────────────
# 语音链路：返回值键名 / 报错可执行 / 对话循环
# ──────────────────────────────────────────────────────────────
class _SpeechTrunk:
    def __init__(self, voice):
        self.base = BASE
        self.config = {}
        self.modules = {"voice": voice}

    def _load_lazy(self, name):
        return self.modules.get(name)


class _VoiceStub:
    def __init__(self, result):
        self.result = result

    def listen(self, seconds=5):
        return self.result


def test_speech_listen_once_normalizes_voice_result():
    """Voice.listen 给的是 text/error，入口必须转成 文字/错误。

    原来直接透传，调用方读 文字 永远拿到空串 —— 识别成功也提示"没听清"。
    """
    from gui.speech import SpeechController
    sc = SpeechController(_SpeechTrunk(_VoiceStub({"ok": True, "text": " 你好 "})), None)
    assert sc.listen_once(1) == {"文字": "你好", "错误": ""}


def test_speech_listen_once_surfaces_backend_error():
    from gui.speech import SpeechController
    sc = SpeechController(
        _SpeechTrunk(_VoiceStub({"ok": False, "error": "缺少pyaudio"})), None)
    r = sc.listen_once(1)
    assert r["文字"] == "" and "pyaudio" in r["错误"]


def test_speech_listen_once_without_module_explains_how_to_install():
    from gui.speech import SpeechController
    sc = SpeechController(_SpeechTrunk(None), None)
    r = sc.listen_once(1)
    assert r["文字"] == ""
    assert "功能扩展组件" in r["错误"]


def test_voice_chat_worker_reads_text_key_and_reports_listen_error():
    from gui.voice_chat_dialog import VoiceChatWorker
    w = VoiceChatWorker(_SpeechTrunk(None))
    try:
        assert w._vad_listen(_VoiceStub({"ok": True, "text": "hi"})) == ("hi", "")
        text, err = w._vad_listen(_VoiceStub({"ok": False, "error": "后端没装"}))
        assert text == "" and err == "后端没装"
    finally:
        w.stop()


def test_voice_error_text_turns_pyaudio_into_actionable_hint():
    from gui.mixins.voice_mixin import _voice_error_text
    text = _voice_error_text("缺少pyaudio")
    assert "pyaudio" in text and "pip" in text
    assert _voice_error_text("没听清，再说一遍试试") == "没听清，再说一遍试试"


def test_speech_listen_once_passes_stop_event_and_falls_back():
    """新模块接受 stop_event；老模块 TypeError 时退回固定时长。"""
    from gui.speech import SpeechController

    class _NewVoice:
        def listen(self, seconds=5, stop_event=None):
            return {"ok": True, "text": "停止:%s" % bool(stop_event)}

    class _OldVoice:
        def listen(self, seconds=5):
            return {"ok": True, "text": "旧接口"}

    sc = SpeechController(_SpeechTrunk(_NewVoice()), None)
    assert sc.listen_once(1, stop_event=object())["文字"] == "停止:True"
    sc = SpeechController(_SpeechTrunk(_OldVoice()), None)
    assert sc.listen_once(1, stop_event=object())["文字"] == "旧接口"


def test_voice_listen_stop_event_returns_no_audio(monkeypatch):
    """按住说话松手太快：没录到帧时给明确错误，而不是转写空音频。"""
    import threading
    import types

    class _Stream:
        def read(self, *a, **k):
            return b"\x00\x00"

        def stop_stream(self):
            pass

        def close(self):
            pass

    class _PA:
        paInt16 = 8

        def open(self, **kw):
            return _Stream()

        def get_sample_size(self, fmt):
            return 2

        def terminate(self):
            pass

    fake = types.SimpleNamespace(PyAudio=_PA, paInt16=8)
    monkeypatch.setitem(sys.modules, "pyaudio", fake)
    v = _voice()
    ev = threading.Event()
    ev.set()
    r = v.listen(seconds=1, stop_event=ev)
    assert r["ok"] is False and "没有录到声音" in r["error"]
