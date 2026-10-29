# -*- coding: utf-8 -*-
"""批次 48.3：语音情绪与首包预算。

不联网、不真的播放：合成函数被替换，只验证参数映射、心境来源、
首包超时回退文本、以及关闭开关后完全回到旧行为。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed import tts as tts_mod   # noqa: E402


class FakeTrunk:
    def __init__(self, base, rules=None, mood="中性"):
        self.base = str(base)
        self.rules = dict(rules or {})
        self.modules = {"personality": type("P", (), {"data": {"mood": mood}})()}

    def rule(self, key, default=None):
        return self.rules.get(key, default)


@pytest.fixture
def engine(tmp_path):
    return tts_mod.TTS(FakeTrunk(tmp_path))


def test_emotion_params(engine):
    assert engine.emotion_params("开心", "on")["rate"] == "+8%"
    assert engine.emotion_params("开心", "off") == {}
    assert engine.emotion_params("中性", "on") == {}


def test_mood_from_personality(tmp_path):
    e = tts_mod.TTS(FakeTrunk(tmp_path, mood="低落"))
    params = e.emotion_params()
    assert params["rate"].startswith("-")


def test_first_packet_timeout_falls_back(engine, monkeypatch):
    async def slow(*a, **k):
        raise tts_mod._FirstPacketTimeout()
    monkeypatch.setattr(engine, "_speak_async", slow)
    out = engine.speak("你好呀")
    assert out["ok"] is False
    assert out["fallback"] == "text"
    assert out["first_packet_ms"] == 1500


def test_speak_records_first_packet(engine, monkeypatch):
    async def fast(text, out_path, params=None, limit_ms=1500):
        with open(out_path, "wb") as f:
            f.write(b"audio")
        return 120
    monkeypatch.setattr(engine, "_speak_async", fast)
    monkeypatch.setattr(tts_mod.os, "startfile", lambda path: None, raising=False)
    out = engine.speak("你好呀", emotion="开心")
    assert out["ok"] is True
    assert out["first_packet_ms"] == 120
    assert out["emotion"] == "开心"
    assert engine.stats()["最近一次"]["first_packet_ms"] == 120
