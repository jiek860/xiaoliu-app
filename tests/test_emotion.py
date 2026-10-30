# -*- coding: utf-8 -*-
"""批次 D5：情绪状态机纯函数测试。"""
from core.chat import emotion


def test_derive_negative():
    got = emotion.derive("今天好累，烦死了")
    assert "negative" in got["tags"]
    assert got["valence"] < 0
    assert got["voice"]


def test_derive_help_priority_over_negative():
    got = emotion.derive("这个报错怎么办啊，烦")
    assert "help" in got["tags"] and "negative" in got["tags"]
    assert got["voice"] == emotion.VOICES["help"]


def test_derive_positive_and_surprise():
    got = emotion.derive("太好了，居然一次就搞定")
    assert "positive" in got["tags"]
    assert "surprise" in got["tags"]


def test_derive_neutral_empty_voice():
    got = emotion.derive("今天天气还行")
    assert got["tags"] == []
    assert got["voice"] == ""


def test_next_state_decays_to_neutral():
    state = emotion.derive("好难过")
    for _ in range(6):
        state = emotion.next_state(state, "嗯")
    assert state["valence"] == 0.0
    assert state["tags"] == []


def test_next_state_overrides_on_new_emotion():
    state = emotion.derive("好累")
    state = emotion.next_state(state, "太好了")
    assert "positive" in state["tags"]
    assert state["valence"] > 0


def test_voice_hint():
    assert emotion.voice_hint({}) == ""
    assert emotion.voice_hint({"tags": [], "voice": ""}) == ""
    assert emotion.voice_hint(
        {"tags": ["negative"], "voice": "温和"}).startswith("本轮语气")
