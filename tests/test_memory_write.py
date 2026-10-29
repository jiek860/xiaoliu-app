# -*- coding: utf-8 -*-
"""记忆 v2 写入侧（批次 43.2）：强信号、5 轮摘要、承诺 due、敏感信息、去重。"""
import json
import os

import pytest

from core.chat import memory_v2 as mv
from core.pipeline.reply_pipeline import ReplyPipeline

NOW = 1_790_000_000.0


class FakeTrunk:
    def __init__(self, base=".", rules=None):
        self.base = str(base)
        self.rules = rules or {}
        self.config = {}
        self.modules = {}
        self._reply_n = 1
        self._recent = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def mem_recent(self, n=6):
        return list(self._recent)[-n:]

    def _load_lazy(self, name):
        return None

    def _log(self, msg):
        pass


def _card_path(base):
    return os.path.join(str(base), "data", "memory_cards.jsonl")


def _read(base):
    path = _card_path(base)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def test_strong_signal_writes_preference(tmp_path):
    result = mv.MemoryV2(str(tmp_path)).remember("记住我喜欢短句", now=NOW)
    assert result["written"] == 1
    assert result["reason"] == "strong"
    card = _read(tmp_path)[0]
    assert card["type"] == "preference"
    assert card["confidence"] == pytest.approx(0.9)


def test_no_signal_and_no_round_does_not_write(tmp_path):
    result = mv.MemoryV2(str(tmp_path)).remember("今天天气不错", rounds=2, now=NOW)
    assert result["written"] == 0
    assert result["cards"] == []
    assert _read(tmp_path) == []


def test_round_multiple_writes_summary(tmp_path):
    result = mv.MemoryV2(str(tmp_path)).remember(
        "在弄代码", rounds=5, recent=["上周在改项目", "今天看了报错"], now=NOW)
    assert result["written"] == 1
    assert result["reason"] == "rounds"
    assert "近几轮聊到" in _read(tmp_path)[0]["text"]


def test_commitment_card_keeps_due(tmp_path):
    mv.MemoryV2(str(tmp_path)).remember("提醒我周五交周报", now=NOW)
    card = _read(tmp_path)[0]
    assert card["type"] == "commitment"
    assert card["due"] == "周五"


def test_commitment_without_due_is_downgraded(tmp_path):
    mv.MemoryV2(str(tmp_path)).remember("我答应你好好吃饭", now=NOW)
    assert _read(tmp_path)[0]["type"] == "event"


def test_sensitive_info_is_redacted(tmp_path):
    mv.MemoryV2(str(tmp_path)).remember("我的密码是abc123", now=NOW)
    text = _read(tmp_path)[0]["text"]
    assert "abc123" not in text
    assert "已隐去" in text


def test_api_key_is_redacted(tmp_path):
    mv.MemoryV2(str(tmp_path)).remember(
        "我的api key是sk-1234567890abc", now=NOW)
    text = _read(tmp_path)[0]["text"]
    assert "sk-1234567890abc" not in text
    assert "已隐去" in text


def test_duplicate_card_is_not_appended(tmp_path):
    store = mv.MemoryV2(str(tmp_path))
    store.remember("记住我喜欢短句", now=NOW)
    store.remember("记住我喜欢短句", now=NOW)
    assert len(_read(tmp_path)) == 1


def test_dry_run_does_not_touch_disk(tmp_path):
    result = mv.MemoryV2(str(tmp_path)).remember(
        "记住我喜欢短句", now=NOW, dry_run=True)
    assert result["written"] == 0
    assert result["reason"] == "strong"
    assert not os.path.exists(_card_path(tmp_path))


def test_multiple_clauses_extract_two_cards(tmp_path):
    result = mv.MemoryV2(str(tmp_path)).remember(
        "我喜欢短句；我讨厌长篇大论", now=NOW)
    assert result["written"] == 2


def test_short_fragments_are_ignored():
    assert mv.extract_cards("嗯。好。", now=NOW) == []


def test_long_text_is_truncated():
    card = mv.make_card("我" * 200, now=NOW)
    assert len(card["text"]) <= 120


def test_pending_commitments_returns_due_card(tmp_path):
    store = mv.MemoryV2(str(tmp_path))
    store.remember("提醒我周五交周报", now=NOW)
    items = store.pending_commitments(now=NOW)
    assert len(items) == 1
    assert items[0]["due"] == "周五"


def test_pending_commitments_skips_expired(tmp_path):
    path = _card_path(tmp_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps({
            "type": "commitment", "text": "提醒我周五交周报", "due": "周五",
            "importance": 0.9, "created_at": NOW - 7200,
            "expires_at": NOW - 1,
        }, ensure_ascii=False) + "\n")
    assert mv.MemoryV2(str(tmp_path)).pending_commitments(now=NOW) == []


def test_append_failure_is_silent(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.mkdir()
    assert mv.append_cards(str(blocker), [mv.make_card("记住我喜欢短句", now=NOW)],
                           now=NOW) == 0


def test_pipeline_on_writes_card(tmp_path):
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "on"})
    out = ReplyPipeline(trunk)._remember("记住我喜欢短句")
    assert out["written"] == 1
    assert len(_read(tmp_path)) == 1


def test_pipeline_shadow_records_without_writing(tmp_path):
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "shadow"})
    out = ReplyPipeline(trunk)._remember("记住我喜欢短句")
    assert out["count"] == 1
    assert out["written"] == 0
    assert not os.path.exists(_card_path(tmp_path))
    shadow = os.path.join(str(tmp_path), "data", "chat_shadow.jsonl")
    rows = [json.loads(line) for line in open(shadow, encoding="utf-8")
            if line.strip()]
    assert [r for r in rows if r.get("kind") == "memory_write"]


def test_pipeline_off_skips_both(tmp_path):
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "off"})
    assert ReplyPipeline(trunk)._remember("记住我喜欢短句") == {}
    assert not os.path.exists(_card_path(tmp_path))
    assert not os.path.exists(
        os.path.join(str(tmp_path), "data", "chat_shadow.jsonl"))


def test_pipeline_uses_recent_for_round_summary(tmp_path):
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "on"})
    trunk._reply_n = 5
    trunk._recent = [{"u": "上周在改项目"}, {"u": "今天看了报错"}]
    ReplyPipeline(trunk)._remember("在弄代码")
    assert "上周在改项目" in _read(tmp_path)[0]["text"]
