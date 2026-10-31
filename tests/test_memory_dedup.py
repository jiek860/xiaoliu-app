# -*- coding: utf-8 -*-
"""B3 记忆去重 / 置信度衰减 单元测试（功能深化二期）。"""
import time
from types import SimpleNamespace

from core.memory_manager import MemoryManager


def _mm(tmp_path):
    return MemoryManager(SimpleNamespace(base=str(tmp_path)))


def test_dedup_merges_similar(tmp_path):
    mm = _mm(tmp_path)
    r1 = mm.add("用户喜欢喝美式咖啡", confidence=0.8)
    assert "merged" not in r1
    r2 = mm.add("用户喜欢喝美式咖啡", confidence=0.5, tags=["偏好"])
    assert r2.get("merged") is True
    assert r2["id"] == r1["id"]
    assert len(mm.list()) == 1
    assert r2["confidence"] > 0.8
    assert "偏好" in r2["tags"]


def test_dedup_disabled_adds_new(tmp_path):
    mm = _mm(tmp_path)
    mm.add("同一句话")
    r2 = mm.add("同一句话", dedup=False)
    assert r2.get("merged") is None
    assert len(mm.list()) == 2


def test_distinct_not_merged(tmp_path):
    mm = _mm(tmp_path)
    mm.add("用户喜欢喝美式咖啡")
    mm.add("用户不喜欢喝咖啡", dedup_threshold=0.95)
    assert len(mm.list()) == 2


def test_effective_confidence_decays(tmp_path):
    mm = _mm(tmp_path)
    rec = mm.add("记忆", confidence=1.0)
    now = rec["last_seen"] + 30 * 86400
    eff = mm.effective_confidence(rec, now=now, half_life_days=30)
    assert 0.4 <= eff <= 0.6


def test_decay_sets_verify_status(tmp_path):
    mm = _mm(tmp_path)
    mm.add("旧记忆", confidence=0.5)
    now = time.time() + 200 * 86400
    res = mm.decay(half_life_days=30, now=now, verify_below=0.3)
    assert res["updated"] == 1
    rows = mm._load()
    assert rows[0]["status"] == "verify"