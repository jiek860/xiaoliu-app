# -*- coding: utf-8 -*-
"""对话状态层（批次 42.1）。"""
import json
import os
from datetime import datetime

from core.chat.state import DialogueState, classify_intent, classify_topic


def _state(tmp_path):
    return DialogueState.load(str(tmp_path))


def test_missing_file_uses_defaults(tmp_path):
    st = _state(tmp_path)
    assert st.summary()["turns"] == 0
    assert st.summary()["intent"] == "chat"
    assert st.summary()["relation"] == "stranger"
    assert not os.path.exists(st.path)


def test_corrupted_file_uses_defaults(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "chat_state.json").write_text("{not json", encoding="utf-8")
    st = _state(tmp_path)
    assert st.summary()["turns"] == 0
    assert st.update("你好")["intent"] == "smalltalk"


def test_malformed_fields_are_sanitized(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "chat_state.json").write_text(json.dumps({
        "user": "坏数据", "affect": {"user_valence": 9, "trust": -3},
        "stats": {"turns": "x"}, "topic": {"recent": "not-a-list"},
        "commitments": {}, "turn": {"unanswered": []},
    }), encoding="utf-8")
    st = _state(tmp_path)
    data = st.data
    assert data["affect"]["user_valence"] == 1.0
    assert data["affect"]["trust"] == 0.0
    assert data["stats"]["turns"] == 0
    assert data["topic"]["recent"] == []
    assert data["commitments"] == []
    assert st.summary()["relation"] == "stranger"


def test_intent_rules():
    assert classify_intent("不对，我是说另一个文件") == "correct"
    assert classify_intent("好烦啊，睡不着") == "vent"
    assert classify_intent("为什么报错了？") == "ask_fact"
    assert classify_intent("帮我改一下") == "request_help"
    assert classify_intent("讲个笑话") == "play"
    assert classify_intent("你好") == "smalltalk"
    assert classify_intent("嗯嗯") == "chat"


def test_topic_rules():
    assert classify_topic("pytest 报错") == "代码"
    assert classify_topic("今天好累") == "情绪"
    assert classify_topic("老板让交周报") == "工作"
    assert classify_topic("周末看电影") == "生活"
    assert classify_topic("嗯") == ""


def test_expects_and_brevity(tmp_path):
    st = _state(tmp_path)
    assert st.update("烦死了")["expects"] == "comfort"
    assert st.update("为什么？")["expects"] == "explanation"
    assert st.update("帮我修一下")["expects"] == "short_action"
    assert st.update("你在吗")["brevity"] == "short"
    assert st.update("这是一段长度刚好超过八个字符但不到四十个字符的普通消息")["brevity"] == "normal"
    assert st.update("长" * 41)["brevity"] == "long"


def test_affect_ema_and_arousal(tmp_path):
    st = _state(tmp_path)
    before = st.summary()["valence"]
    out = st.update("太崩溃了！！好烦！")
    assert out["valence"] < before
    assert out["arousal"] > 0.3
    st.update("太好了，搞定了")
    assert st.summary()["valence"] > out["valence"]


def test_topic_switch_needs_two_turns(tmp_path):
    st = _state(tmp_path)
    assert st.update("pytest 报错")["topic"] == "代码"
    assert st.update("今天好累")["topic"] == "代码"     # 只出现一次不切
    assert st.update("还是好累")["topic"] == "情绪"     # 连续两轮才切


def test_relation_stage_grows(tmp_path):
    st = _state(tmp_path)
    for _ in range(8):
        st.update("嗯")
    assert st.summary()["relation"] == "familiar"
    for _ in range(22):
        st.update("嗯")
    assert st.summary()["relation"] == "close"
    assert st.summary()["turns"] == 30


def test_commitment_created_with_due(tmp_path):
    st = _state(tmp_path)
    now = datetime(2026, 10, 29, 10, 0).timestamp()
    out = st.update("明天记得提醒我交周报", now=now)
    assert out["commitments"] == 1
    item = st.data["commitments"][0]
    assert item["due"] == "2026-10-30T09:00"
    assert item["status"] == "open"


def test_commitment_dedup_and_overdue(tmp_path):
    st = _state(tmp_path)
    now = datetime(2026, 10, 29, 10, 0).timestamp()
    st.update("明天记得提醒我交周报", now=now)
    st.update("明天记得提醒我交周报", now=now + 60)
    assert len(st.data["commitments"]) == 1
    out = st.update("嗯", now=now + 3 * 86400)
    assert out["commitments"] == 0
    assert st.data["commitments"][0]["status"] == "overdue"


def test_unanswered_questions_capped(tmp_path):
    st = _state(tmp_path)
    for i in range(4):
        st.update("为什么第%d个会这样？" % i)
    unanswered = st.data["turn"]["unanswered"]
    assert len(unanswered) == 3
    assert "第0个" not in unanswered[-1]


def test_save_and_load_roundtrip(tmp_path):
    st = _state(tmp_path)
    st.update("帮我写个函数")
    assert st.save() is True
    assert os.path.exists(st.path)
    assert not os.path.exists(st.path + ".tmp")
    again = _state(tmp_path)
    assert again.summary()["turns"] == 1
    assert again.summary()["intent"] == "request_help"
    assert again.data["session_id"] == st.data["session_id"]


def test_save_failure_is_silent(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("x", encoding="utf-8")
    st = DialogueState(base=str(tmp_path), path=str(blocker / "chat_state.json"))
    assert st.save() is False


def test_update_never_raises(tmp_path):
    class Boom:
        def __str__(self):
            raise RuntimeError("boom")

    st = _state(tmp_path)
    out = st.update(Boom())
    assert isinstance(out, dict)
    assert out["turns"] == 0


def test_update_with_none(tmp_path):
    st = _state(tmp_path)
    assert st.update(None)["intent"] == "chat"


class FakeTrunk:
    def __init__(self, base, mode="shadow"):
        self.base = str(base)
        self._mode = mode

    def rule(self, key, default=None):
        if key == "聊天.状态层":
            return self._mode
        return default


def test_pipeline_state_off_does_nothing(tmp_path):
    from core.pipeline.reply_pipeline import ReplyPipeline

    pipe = ReplyPipeline(FakeTrunk(tmp_path, mode="off"))
    assert pipe._track_state("你好") == {}
    assert not os.path.exists(os.path.join(str(tmp_path), "data", "chat_state.json"))


def test_pipeline_state_shadow_writes_and_returns_summary(tmp_path):
    from core.pipeline.reply_pipeline import ReplyPipeline

    pipe = ReplyPipeline(FakeTrunk(tmp_path))
    summary = pipe._track_state("帮我修一下这个报错")
    assert summary["intent"] == "request_help"
    assert summary["turns"] == 1
    assert summary["session"]
    assert os.path.exists(os.path.join(str(tmp_path), "data", "chat_state.json"))


def test_pipeline_state_invalid_mode_falls_back_to_shadow(tmp_path):
    from core.pipeline.reply_pipeline import ReplyPipeline

    pipe = ReplyPipeline(FakeTrunk(tmp_path, mode="loud"))
    assert pipe._state_mode() == "shadow"
    assert pipe._track_state("嗯")["turns"] == 1


def test_pipeline_state_rule_error_is_silent(tmp_path):
    from core.pipeline.reply_pipeline import ReplyPipeline

    class Broken(FakeTrunk):
        def rule(self, key, default=None):
            raise RuntimeError("boom")

    pipe = ReplyPipeline(Broken(tmp_path))
    assert pipe._state_mode() == "shadow"
    assert pipe._track_state("嗯")["turns"] == 1
    assert os.path.exists(os.path.join(str(tmp_path), "data", "chat_state.json"))
