# -*- coding: utf-8 -*-
"""A4 命令面板排序/别名 单元测试（功能深化二期）。"""
from core import palette_rank


def test_record_use_increments(tmp_path):
    base = str(tmp_path)
    rec = palette_rank.record_use(base, "cap:send")
    assert rec["count"] == 1
    rec = palette_rank.record_use(base, "cap:send")
    assert palette_rank.frequency(base, "cap:send") == 2


def test_recency_fresh_vs_old(tmp_path):
    base = str(tmp_path)
    palette_rank.record_use(base, "a", now=1000.0)
    fresh = palette_rank.recency(base, "a", now=1000.0)
    old = palette_rank.recency(base, "a", now=1000.0 + 30 * 24 * 3600)
    assert fresh > old
    assert 0.0 <= old <= fresh <= 1.0


def test_score_prefers_frequent(tmp_path):
    base = str(tmp_path)
    for _ in range(5):
        palette_rank.record_use(base, "hot")
    palette_rank.record_use(base, "cold")
    assert palette_rank.score(base, "hot") > palette_rank.score(base, "cold")


def test_unknown_entry_score_is_zero(tmp_path):
    base = str(tmp_path)
    assert palette_rank.score(base, "nope") == 0.0


def test_alias_save_and_hits(tmp_path):
    base = str(tmp_path)
    palette_rank.save_alias(base, "cap:send", "发消息")
    hits = palette_rank.alias_hits(base, "发")
    assert "cap:send" in hits
    assert palette_rank.alias_hits(base, "") == []


def test_alias_dedup(tmp_path):
    base = str(tmp_path)
    palette_rank.save_alias(base, "cap:send", "发消息")
    palette_rank.save_alias(base, "cap:send", "发消息")
    assert palette_rank.load_aliases(base)["cap:send"] == ["发消息"]