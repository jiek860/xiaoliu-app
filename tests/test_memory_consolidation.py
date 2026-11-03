# -*- coding: utf-8 -*-
"""第 4 批：分层记忆（深度①）、会话结束记忆巩固（深度②）、冲突留痕（深度③）。"""
import json
import os
import sys
import time
from types import SimpleNamespace

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.chat import memory_v2 as mv  # noqa: E402
from core.dream_system import DreamSystem  # noqa: E402
from core.memory_manager import MemoryManager  # noqa: E402
from core.pipeline.memory_consolidation import (  # noqa: E402
    consolidate_session, load_conflicts)

NOW = time.time()


def _cards(base):
    path = os.path.join(str(base), "data", "memory_cards.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _mm(tmp_path):
    return MemoryManager(SimpleNamespace(base=str(tmp_path)))


# ---------------------------------------------------------------- 分层记忆

def test_layer_is_inferred_from_type_and_text():
    assert mv.infer_layer("我喜欢短句", "preference") == "semantic"
    assert mv.infer_layer("提醒我周五交周报", "commitment") == "episodic"
    assert mv.infer_layer("我住在杭州") == "semantic"
    assert mv.infer_layer("今天随手记一句") == "work"


def test_normalize_and_summary_assign_layer():
    card = mv.normalize({"facts": ["偏好:喜欢短句"], "time": NOW}, now=NOW)
    assert card["layer"] == "semantic"
    summary = mv.summarize_cards(["聊了代码", "聊了测试"], now=NOW)[0]
    assert summary["layer"] == "work"


def test_memory_manager_adds_layer_and_filters(tmp_path):
    mm = _mm(tmp_path)
    mm.add("我喜欢短句")
    mm.add("提醒我周五交周报")
    mm.add("今天随手记一句")
    assert [r["text"] for r in mm.list(layer="semantic")] == ["我喜欢短句"]
    assert [r["text"] for r in mm.list(layer="episodic")] == ["提醒我周五交周报"]
    assert [r["text"] for r in mm.list(layer="work")] == ["今天随手记一句"]
    counts = mm.layers()
    assert counts["合计"] == 3
    assert counts["semantic"]["条数"] == 1


def test_recall_prefers_semantic_and_episodic(tmp_path):
    mm = _mm(tmp_path)
    mm.add("我喜欢短句")
    mm.add("今天随手记一句短句的事")
    hits = mm.recall("短句")
    assert [r["text"] for r in hits] == ["我喜欢短句"]      # 工作记忆默认不召回
    assert [r["text"] for r in mm.recall("短句", layers=("work",))] \
        == ["今天随手记一句短句的事"]


def test_memory_manager_upgrades_layer_but_never_downgrades(tmp_path):
    mm = _mm(tmp_path)
    first = mm.add("我喜欢短句")
    assert first["layer"] == "semantic"
    merged = mm.add("我喜欢短句", layer="work")            # 显式给低层不降级
    assert merged.get("merged") is True
    assert merged["layer"] == "semantic"


def test_legacy_rows_without_layer_are_inferred(tmp_path):
    mm = _mm(tmp_path)
    path = os.path.join(str(tmp_path), "data", "memory_cards.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps({"id": "old", "text": "我住在杭州"},
                            ensure_ascii=False) + "\n")
    rows = mm.list()
    assert rows and rows[0]["layer"] == "semantic"


# ---------------------------------------------------------------- 会话结束巩固

def test_consolidate_writes_strong_signals(tmp_path):
    res = consolidate_session([{"role": "user", "content": "记住我喜欢短句"},
                               {"role": "user", "content": "我住在杭州"}],
                              base=tmp_path, now=NOW)
    assert res["written"] >= 1
    texts = [c["text"] for c in _cards(tmp_path)]
    assert any("短句" in t for t in texts)
    assert any("杭州" in t for t in texts)


def test_consolidate_accepts_pair_shape(tmp_path):
    res = consolidate_session([{"u": "我喜欢用深色主题", "a": "记住了"}],
                              base=tmp_path, now=NOW)
    assert res["written"] == 1
    assert "深色主题" in _cards(tmp_path)[0]["text"]


def test_consolidate_skips_duplicates_of_existing(tmp_path):
    consolidate_session([{"role": "user", "content": "记住我喜欢短句"}],
                        base=tmp_path, now=NOW)
    again = consolidate_session([{"role": "user", "content": "记住我喜欢短句"}],
                                base=tmp_path, now=NOW + 60)
    assert again["written"] == 0
    assert len(_cards(tmp_path)) == 1
    assert again["skipped"]


def test_consolidate_writes_session_summary_for_long_chat(tmp_path):
    rows = [{"role": "user", "content": "今天在改登录页"},
            {"role": "user", "content": "报错是个 NoneType"},
            {"role": "user", "content": "后来补了判空"}]
    res = consolidate_session(rows, base=tmp_path, now=NOW)
    texts = [c["text"] for c in _cards(tmp_path)]
    assert any(t.startswith("近几轮聊到") for t in texts)
    assert any(c.get("layer") == "work" for c in res["cards"])


def test_consolidate_dry_run_writes_nothing(tmp_path):
    res = consolidate_session([{"role": "user", "content": "记住我喜欢短句"}],
                              base=tmp_path, now=NOW, dry_run=True)
    assert res["written"] == 0
    assert not os.path.exists(
        os.path.join(str(tmp_path), "data", "memory_cards.jsonl"))
    assert res["cards"]


def test_consolidate_empty_messages(tmp_path):
    res = consolidate_session([], base=tmp_path, now=NOW)
    assert res["written"] == 0 and res["cards"] == []


def test_conflict_is_resolved_and_logged(tmp_path):
    path = os.path.join(str(tmp_path), "data", "memory_cards.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps({"id": "m_old", "type": "preference",
                             "text": "我喜欢短句", "created_at": NOW - 3600},
                            ensure_ascii=False) + "\n")
    res = consolidate_session([{"role": "user", "content": "我不喜欢短句"}],
                              base=tmp_path, now=NOW)
    assert res["written"] == 1
    assert res["conflicts"], "正反偏好应算冲突并留痕"
    assert res["conflicts"][0]["losers"] == ["m_old"]
    logged = load_conflicts(tmp_path)
    assert logged and logged[-1]["winner"] == res["cards"][0]["id"]


def test_load_conflicts_missing_file_is_empty(tmp_path):
    assert load_conflicts(tmp_path) == []


# ---------------------------------------------------------------- DreamSystem 接线

def test_dream_consolidate_writes_memory_and_dream(tmp_path):
    ds = DreamSystem(SimpleNamespace(base=str(tmp_path)))
    res = ds.consolidate([{"role": "user", "content": "记住我喜欢短句"}],
                         now=NOW)
    assert res["written"] == 1
    dreams = ds.get_recent_dreams()
    assert any("长期记忆" in str(d.get("dream", "")) for d in dreams)


def test_dream_consolidate_does_not_dream_when_nothing_written(tmp_path):
    ds = DreamSystem(SimpleNamespace(base=str(tmp_path)))
    res = ds.consolidate([], now=NOW)
    assert res["written"] == 0
    assert ds.get_recent_dreams() == []


def test_dream_consolidate_tolerates_bad_input(tmp_path):
    ds = DreamSystem(SimpleNamespace(base=str(tmp_path)))
    assert ds.consolidate(None, now=NOW)["written"] == 0
