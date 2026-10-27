# -*- coding: utf-8 -*-
"""Incremental permission-aware RAG tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.rag_pipeline import KnowledgeBase  # noqa: E402


def test_ingest_search_and_citations(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "guide.md"
    f.write_text("小6智能体支持插件、MCP 和电脑控制。\n\n知识库需要引用定位。",
                 encoding="utf-8")
    kb = KnowledgeBase(tmp_path, "team")
    r = kb.ingest_file(f)
    assert r["ok"] and r["chunks"] >= 1
    hits = kb.search("插件 MCP", role="viewer", top_k=3)
    assert hits
    assert hits[0]["source"] == "docs/guide.md"
    assert "docs/guide.md" in hits[0]["citation"]
    assert hits[0]["offset"] >= 0
    assert kb.stats()["sources"] == 1


def test_incremental_skip_and_force_reindex(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "a.txt"
    f.write_text("alpha beta", encoding="utf-8")
    kb = KnowledgeBase(tmp_path, "inc")
    r1 = kb.ingest_file(f)
    r2 = kb.ingest_file(f)
    assert r1["ok"] and r2["skipped"] is True
    assert kb.stats()["chunks"] == r1["chunks"]
    f.write_text("alpha beta gamma", encoding="utf-8")
    r3 = kb.ingest_file(f)
    assert r3["ok"] and not r3["skipped"]
    assert kb.stats()["sources"] == 1


def test_acl_blocks_unauthorized_role(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "secret.txt"
    f.write_text("secret budget plan", encoding="utf-8")
    kb = KnowledgeBase(tmp_path, "acl")
    kb.ingest_file(f, acl_roles=["admin", "editor"])
    assert kb.search("budget", role="viewer") == []
    assert kb.search("budget", role="editor")


def test_delete_source_removes_chunks(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    f = docs / "a.txt"
    f.write_text("delete me", encoding="utf-8")
    kb = KnowledgeBase(tmp_path, "del")
    kb.ingest_file(f)
    assert kb.delete_source("docs/a.txt") is True
    assert kb.stats()["chunks"] == 0


def test_directory_ingest_only_supported_extensions(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello markdown", encoding="utf-8")
    (docs / "b.bin").write_bytes(b"ignore")
    kb = KnowledgeBase(tmp_path, "dir")
    r = kb.ingest_directory(docs)
    assert r["files"] == 1
    assert kb.stats()["sources"] == 1


def test_sources_list_for_management_ui(tmp_path):
    """管理界面要能列出已索引来源：手打相对路径删除是不可用的交互。"""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha", encoding="utf-8")
    (docs / "b.md").write_text("beta", encoding="utf-8")
    kb = KnowledgeBase(tmp_path, "ui")
    kb.ingest_directory(docs, acl_roles=["admin"])
    got = kb.sources()
    assert [x["source"] for x in got] == ["docs/a.md", "docs/b.md"]
    assert all(x["chunks"] >= 1 for x in got)
    assert got[0]["acl_roles"] == ["admin"]
    assert kb.sources()[0]["source"] in kb._manifest


def test_summarize_ingest_is_readable():
    """导入结果给人话，不是 JSON 转储。"""
    from gui.rag_dialog import summarize_ingest

    single = summarize_ingest({"ok": True, "source": "docs/a.md", "chunks": 3})
    assert "docs/a.md" in single and "3" in single
    skipped = summarize_ingest({"ok": True, "source": "docs/a.md",
                                "chunks": 3, "skipped": True})
    assert "没有变化" in skipped
    bulk = summarize_ingest({"ok": True, "files": 3, "results": [
        {"source": "docs/a.md", "ok": True, "skipped": False},
        {"source": "docs/b.md", "ok": True, "skipped": True},
        {"source": "docs/c.pdf", "ok": False, "error": "解析失败"},
    ]})
    assert "新增/更新 1 个" in bulk
    assert "跳过 1 个" in bulk
    assert "docs/c.pdf" in bulk and "解析失败" in bulk
    failed = summarize_ingest({"ok": False, "error": "磁盘满了"})
    assert "磁盘满了" in failed
