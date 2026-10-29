# -*- coding: utf-8 -*-
"""影子状态记录（批次 41.4）。"""
import json
import os

from core.pipeline.context_builder import ContextBuilder


class FakeTrunk:
    def __init__(self, base, enabled=True):
        self.base = str(base)
        self._enabled = enabled

    def rule(self, key, default=None):
        if key == "聊天.影子状态":
            return self._enabled
        return default


def _read_lines(path):
    with open(path, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def test_record_shadow_writes_jsonl(tmp_path):
    trunk = FakeTrunk(tmp_path)
    ctx = ContextBuilder(trunk)
    ok = ctx.record_shadow({"text": "今天好累", "intent": "vent"})
    assert ok is True
    rows = _read_lines(ctx.shadow_path())
    assert len(rows) == 1
    assert rows[0]["text"] == "今天好累"
    assert rows[0]["intent"] == "vent"
    assert "ts" in rows[0]


def test_shadow_switch_off(tmp_path):
    ctx = ContextBuilder(FakeTrunk(tmp_path, enabled=False))
    assert ctx.record_shadow({"text": "hi"}) is False
    assert not os.path.exists(ctx.shadow_path())


def test_guess_intent_and_topic():
    ctx = ContextBuilder(FakeTrunk("."))
    assert ctx.guess_intent("不对，我是说另一个文件") == "correct"
    assert ctx.guess_intent("好烦啊") == "vent"
    assert ctx.guess_intent("为什么会报错") == "ask_fact"
    assert ctx.guess_intent("帮我改一下") == "request_help"
    assert ctx.guess_intent("你好") == "smalltalk"
    assert ctx.guess_intent("随便说说") == "chat"
    assert ctx.guess_topic("pytest 报错") == "代码"
    assert ctx.guess_topic("今天被夸了") == "情绪"
    assert ctx.guess_topic("老板让我交周报") == "工作"
    assert ctx.guess_topic("周末看电影") == "生活"
    assert ctx.guess_topic("嗯") == "闲聊"


def test_shadow_rotation(tmp_path, monkeypatch):
    trunk = FakeTrunk(tmp_path)
    ctx = ContextBuilder(trunk)
    monkeypatch.setattr(ContextBuilder, "_SHADOW_MAX_BYTES", 10)
    assert ctx.record_shadow({"text": "第一行"}) is True
    assert ctx.record_shadow({"text": "第二行"}) is True
    assert os.path.exists(ctx.shadow_path() + ".1")
    rows = _read_lines(ctx.shadow_path())
    assert rows[-1]["text"] == "第二行"


def test_record_shadow_never_raises(tmp_path):
    class Broken:
        base = str(tmp_path)

        def rule(self, key, default=None):
            raise RuntimeError("boom")

    ctx = ContextBuilder(Broken())
    assert ctx.record_shadow({"text": "x"}) in (True, False)
