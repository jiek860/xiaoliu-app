# -*- coding: utf-8 -*-
"""A1 发送草稿 / 输入历史 单元测试（功能深化二期）。"""
from core import draft_store


def test_save_and_load_draft(tmp_path):
    base = str(tmp_path)
    assert draft_store.save_draft(base, "s1", "草稿内容") is True
    assert draft_store.load_draft(base, "s1") == "草稿内容"
    assert draft_store.has_draft(base, "s1") is True


def test_empty_text_clears_draft(tmp_path):
    base = str(tmp_path)
    draft_store.save_draft(base, "s1", "x")
    assert draft_store.save_draft(base, "s1", "   ") is True
    assert draft_store.load_draft(base, "s1") == ""


def test_clear_draft_idempotent(tmp_path):
    base = str(tmp_path)
    assert draft_store.clear_draft(base, "none") is True
    draft_store.save_draft(base, "s1", "y")
    assert draft_store.clear_draft(base, "s1") is True
    assert draft_store.load_draft(base, "s1") == ""


def test_session_name_is_sanitized(tmp_path):
    base = str(tmp_path)
    draft_store.save_draft(base, "../evil/x", "z")
    # 越界路径不应生成在 base 之外，且能正常读回
    assert draft_store.load_draft(base, "../evil/x") == "z"


def test_history_push_dedup_and_limit(tmp_path):
    base = str(tmp_path)
    draft_store.push_history(base, "第一条")
    draft_store.push_history(base, "第一条")       # 与上一条重复 -> 不重复记
    assert draft_store.get_history(base) == ["第一条"]
    for i in range(60):
        draft_store.push_history(base, "m%d" % i)
    got = draft_store.get_history(base)
    assert len(got) == draft_store.HISTORY_LIMIT
    assert got[-1] == "m59"


def test_history_clear(tmp_path):
    base = str(tmp_path)
    draft_store.push_history(base, "a")
    assert draft_store.clear_history(base) is True
    assert draft_store.get_history(base) == []