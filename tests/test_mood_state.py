# -*- coding: utf-8 -*-
"""E2 情绪状态机 单元测试（功能深化二期）。"""
from core import mood_state


def test_detect_moods():
    assert mood_state.detect("太好了，太棒了") == "excited"
    assert mood_state.detect("烦死了，又失败") == "frustrated"
    assert mood_state.detect("有点焦虑，怕来不及") == "anxious"
    assert mood_state.detect("今天天气不错") == "calm"


def test_update_and_history():
    st = mood_state.MoodState()
    assert st.update("太好了") == "excited"
    assert st.update("又失败了，烦") == "frustrated"
    assert st.history[-1] == ("excited", "frustrated")


def test_signals_override():
    st = mood_state.MoodState()
    assert st.update("随便", signals={"mood": "anxious"}) == "anxious"


def test_hint_weight_and_negative():
    st = mood_state.MoodState("frustrated")
    assert st.hint_weight() == 1.2
    assert st.is_negative() is True
    st.reset()
    assert st.mood == "calm" and st.hint_weight() == 1.0


def test_invalid_mood_falls_back():
    st = mood_state.MoodState("bogus")
    assert st.mood == "calm"
    assert st.update("x", signals={"mood": "bogus"}) == "calm"