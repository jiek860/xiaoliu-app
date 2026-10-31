# -*- coding: utf-8 -*-
"""B2 知识库溯源 / 过期降权 / 查询改写 单元测试（功能深化二期）。"""
import time

from core.rag_pipeline import KnowledgeBase, rewrite_query


def test_rewrite_query_followup_only():
    assert rewrite_query("它呢", ["刚才说的是苹果"]) == "刚才说的是苹果 它呢"
    assert rewrite_query("继续", ["上一话题"]) == "上一话题 继续"
    # 不是追问句 -> 不改写
    assert rewrite_query("苹果", ["上一话题"]) == "苹果"
    assert rewrite_query("", ["x"]) == ""
    assert rewrite_query("问题", []) == "问题"


def _kb(tmp_path):
    kb = KnowledgeBase(str(tmp_path))
    kb._chunks = [{"id": "c1", "text": "这里有关键词苹果和香蕉",
                   "source": "doc.md", "page": None, "offset": 0,
                   "acl_roles": [], "metadata": {}}]
    kb._manifest = {"doc.md": {"chunks": 1, "acl_roles": [], "expires_at": 0}}
    return kb


def test_search_returns_citation_and_not_expired(tmp_path):
    kb = _kb(tmp_path)
    hits = kb.search("苹果", top_k=1)
    assert hits and hits[0]["chunk_id"] == "c1"
    assert hits[0]["citation"] == "doc.md"
    assert hits[0]["expired"] is False


def test_set_expiry_marks_and_downweights(tmp_path):
    kb = _kb(tmp_path)
    before = kb.search("苹果", top_k=1)[0]
    # 设为已过期（时间戳在过去）
    r = kb.set_expiry("doc.md", time.time() - 10)
    assert r["ok"] is True
    after = kb.search("苹果", top_k=1)[0]
    assert after["expired"] is True
    # 过期后分数应明显下降
    assert after["score"] < before["score"]


def test_set_expiry_missing_source(tmp_path):
    kb = _kb(tmp_path)
    r = kb.set_expiry("nope.md", 1)
    assert r["ok"] is False


def test_sources_include_expires_at(tmp_path):
    kb = _kb(tmp_path)
    kb.set_expiry("doc.md", time.time() + 100)
    srcs = kb.sources()
    assert srcs and srcs[0]["source"] == "doc.md"
    assert srcs[0]["expires_at"] > 0