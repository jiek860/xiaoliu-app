# -*- coding: utf-8 -*-
"""记忆 v2 统一入口（批次 43.1）：schema 兼容、排序、预算、去重、管线开关。"""
import json
import os
import time

import pytest

from core.chat import memory_v2 as mv
from core.pipeline.context_builder import ContextBuilder


class FakeTrunk:
    def __init__(self, base=".", rules=None, modules=None):
        self.base = str(base)
        self.rules = rules or {}
        self.config = {}
        self.modules = modules or {}
        self.logs = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _load_lazy(self, name):
        return self.modules.get(name)

    def _log(self, msg):
        self.logs.append(str(msg))


class FakeMemoryLoop:
    def recall(self, query, top_k=2, hours=48):
        return [{"type": "情景", "scene": "编程",
                 "time": "2026-10-29 10:00", "text": "修了个 bug"}]


def _write_cards(base, rows, name="memory_cards.jsonl"):
    folder = os.path.join(str(base), "data")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write((row if isinstance(row, str)
                      else json.dumps(row, ensure_ascii=False)) + "\n")
    return path


NOW = 1_790_000_000.0


def test_normalize_legacy_facts_card():
    card = mv.normalize({"facts": ["偏好:喜欢Python", "计划:周末爬山"],
                         "time": NOW, "feelings": "平静"}, now=NOW)
    assert card["text"] == "偏好:喜欢Python；计划:周末爬山"
    assert card["type"] == "preference"
    assert card["importance"] == pytest.approx(0.8)
    assert card["source"] == "chat"
    assert card["expires_at"] is None


def test_normalize_keeps_v2_fields():
    raw = {"id": "m_1", "type": "commitment", "text": "答应周五交稿",
           "subject": "user", "confidence": 0.9, "importance": 0.95,
           "created_at": NOW - 3600, "last_used_at": NOW,
           "source": "chat", "expires_at": NOW + 86400,
           "conflicts_with": ["m_0"], "topic": "工作"}
    card = mv.normalize(raw, now=NOW)
    assert card["id"] == "m_1"
    assert card["confidence"] == pytest.approx(0.9)
    assert card["expires_at"] == NOW + 86400
    assert card["conflicts_with"] == ["m_0"]
    assert card["topic"] == "工作"


def test_normalize_rejects_empty_or_bad():
    assert mv.normalize(None) is None
    assert mv.normalize({"facts": []}) is None
    assert mv.normalize({"text": "   "}) is None


def test_card_id_is_stable_and_dedupes():
    assert mv.card_id("喜欢短句") == mv.card_id("喜欢短句")
    assert mv.card_id("喜欢短句") != mv.card_id("讨厌短句")


def test_load_cards_skips_bad_lines(tmp_path):
    _write_cards(tmp_path, [
        {"facts": ["偏好:喜欢短句"], "time": NOW},
        "{bad json",
        {"facts": ["事实:住在杭州"], "time": NOW},
    ])
    rows = mv.load_cards(os.path.join(str(tmp_path), "data", "memory_cards.jsonl"))
    assert len(rows) == 2


def test_load_cards_missing_file_is_empty(tmp_path):
    assert mv.load_cards(os.path.join(str(tmp_path), "data", "nope.jsonl")) == []


def test_relevance_ranks_matching_first(tmp_path):
    _write_cards(tmp_path, [
        {"facts": ["事实:住在杭州"], "time": NOW},
        {"facts": ["偏好:喜欢短句"], "time": NOW},
    ])
    cards = mv.MemoryV2(str(tmp_path)).recall("我喜欢什么样的句子", now=NOW)
    assert len(cards) == 1
    assert "短句" in cards[0]["text"]


def test_unrelated_card_is_not_injected(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢Python"], "time": NOW}])
    assert mv.MemoryV2(str(tmp_path)).recall("今天天气如何", now=NOW) == []


def test_topic_match_includes_wordless_card(tmp_path):
    _write_cards(tmp_path, [{"facts": ["周末去爬山"], "time": NOW}])
    cards = mv.MemoryV2(str(tmp_path)).recall("嗯", topic="生活", now=NOW)
    assert len(cards) == 1
    assert "爬山" in cards[0]["text"]


def test_recency_uses_sixty_day_half_life():
    assert mv.recency(NOW - 60 * 86400, NOW) == pytest.approx(0.5)
    assert mv.recency(NOW - 120 * 86400, NOW) == pytest.approx(0.25)
    assert mv.recency(NOW + 100, NOW) == pytest.approx(1.0)


def test_score_weights_follow_design():
    card = {"text": "喜欢短句", "importance": 0.8, "created_at": NOW,
            "topic": "生活"}
    value, rel, topic_hit = mv.score(card, "喜欢短句", "生活", NOW)
    expected = (0.45 * rel + 0.25 * 0.8 + 0.20 * 1.0 + 0.10 * 1.0)
    assert rel == pytest.approx(1.0)
    assert topic_hit == 1.0
    assert value == pytest.approx(round(expected, 4))


def test_budget_limits_cards_and_chars(tmp_path):
    rows = [{"facts": ["偏好:喜欢第%d种写法" % i], "time": NOW} for i in range(5)]
    _write_cards(tmp_path, rows)
    cards = mv.MemoryV2(str(tmp_path)).recall("喜欢什么写法", limit=3,
                                              max_chars=70, now=NOW)
    assert 0 < len(cards) <= 3
    text = mv.MemoryV2(str(tmp_path)).render(cards)
    assert len(text) <= 70
    assert all(line.startswith("【记忆】") for line in text.splitlines())
    assert all("\n" not in line for line in text.splitlines())


def test_commit_blocks_same_card_for_24h(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢短句"], "time": NOW}])
    store = mv.MemoryV2(str(tmp_path))
    cards = store.recall("喜欢短句", now=NOW)
    assert cards
    assert store.commit(cards, now=NOW) is True
    assert store.recall("喜欢短句", now=NOW + 3600) == []
    later = store.recall("喜欢短句", now=NOW + 25 * 3600)
    assert later


def test_expired_card_is_skipped(tmp_path):
    _write_cards(tmp_path, [{"facts": ["这周在出差"], "time": NOW,
                             "expires_at": NOW - 1}])
    assert mv.MemoryV2(str(tmp_path)).recall("出差", now=NOW) == []


def test_state_roundtrip_and_corrupt_fallback(tmp_path):
    path = os.path.join(str(tmp_path), "data", "state.json")
    assert mv.save_state(path, {"version": 2, "injected": {"m_1": NOW}}) is True
    assert mv.load_state(path)["injected"]["m_1"] == NOW
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("{bad")
    assert mv.load_state(path) == {"version": 2, "injected": {}}


def test_state_write_failure_is_silent(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.mkdir()
    assert mv.save_state(str(blocker), {"injected": {}}) is False


def test_context_builder_shadow_keeps_legacy_and_records(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢短句"], "time": time.time()}])
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "shadow"},
                      modules={"memory_loop": FakeMemoryLoop()})
    out = ContextBuilder(trunk)._ctx_memory("我喜欢什么样的句子")
    assert "情景记忆" in out
    shadow = os.path.join(str(tmp_path), "data", "chat_shadow.jsonl")
    rows = [json.loads(line) for line in open(shadow, encoding="utf-8") if line.strip()]
    preview = [r for r in rows if r.get("kind") == "memory_v2"]
    assert preview and "短句" in preview[-1]["preview"]
    state = os.path.join(str(tmp_path), "data", "memory_v2_state.json")
    assert not os.path.exists(state)


def test_context_builder_on_replaces_legacy(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢短句"], "time": time.time()}])
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "on"},
                      modules={"memory_loop": FakeMemoryLoop()})
    out = ContextBuilder(trunk)._ctx_memory("我喜欢什么样的句子")
    assert "【记忆】" in out
    assert "情景记忆" not in out
    assert os.path.exists(
        os.path.join(str(tmp_path), "data", "memory_v2_state.json"))


def test_context_builder_off_uses_legacy_only(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢短句"], "time": time.time()}])
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "off"},
                      modules={"memory_loop": FakeMemoryLoop()})
    assert "情景记忆" in ContextBuilder(trunk)._ctx_memory("我喜欢什么样的句子")
    assert not os.path.exists(
        os.path.join(str(tmp_path), "data", "chat_shadow.jsonl"))


def test_context_builder_corrupt_cards_falls_back(tmp_path):
    _write_cards(tmp_path, ["{bad json"])
    trunk = FakeTrunk(tmp_path, rules={"记忆.v2": "on"},
                      modules={"memory_loop": FakeMemoryLoop()})
    assert "情景记忆" in ContextBuilder(trunk)._ctx_memory("喜欢什么")


def test_context_builder_zero_limit_disables_injection(tmp_path):
    _write_cards(tmp_path, [{"facts": ["偏好:喜欢短句"], "time": time.time()}])
    trunk = FakeTrunk(tmp_path,
                      rules={"记忆.v2": "on", "记忆.注入张数": 0},
                      modules={"memory_loop": FakeMemoryLoop()})
    assert "情景记忆" in ContextBuilder(trunk)._ctx_memory("喜欢什么")


def test_memory_mode_accepts_bool_and_junk():
    assert ContextBuilder(FakeTrunk(rules={"记忆.v2": True})).memory_mode() == "on"
    assert ContextBuilder(FakeTrunk(rules={"记忆.v2": False})).memory_mode() == "off"
    assert ContextBuilder(FakeTrunk(rules={"记忆.v2": "??"})).memory_mode() == "shadow"
