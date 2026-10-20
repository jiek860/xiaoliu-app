# -*- coding: utf-8 -*-
"""语音模块：缺依赖、坏路径和成功转写路径。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

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