# -*- coding: utf-8 -*-
"""KnowledgeQnA：文档导入、检索、来源引用、索引重建和问答。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.knowledge_qa import KnowledgeQnA  # noqa: E402


class _LLM:
    def __init__(self):
        self.messages = []

    def chat(self, message):
        self.messages.append(message)
        return "知识库回答"


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {}
        self.modules = {"llm": _LLM()}


class _FakeIndex:
    def __init__(self, _root):
        self.added = []
        self.cleared = False

    def add_many(self, rows):
        self.added.extend(rows)

    def clear(self):
        self.cleared = True

    def clear_all(self):
        self.cleared = True

    def search(self, _query, _top_k):
        return [{"source": "s", "page": 1, "text": "命中"}]

    def delete_source(self, _source):
        return None

    def stats(self):
        return {"rows": len(self.added)}


def _qa(tmp_path):
    return KnowledgeQnA(_Trunk(tmp_path))


def test_knowledge_docs_crud(tmp_path):
    q = _qa(tmp_path)
    assert q.add_doc("测试 文档", "Python 和知识库")["已添加"]
    assert q.list_docs()["文档数"] == 1
    assert q.list_documents()["文档数"] == 1
    assert q.search_doc("Python")["找到"] == 1
    assert "Python" in q.read_doc("测试_文档.txt")["内容"]
    assert q.stats()["文档数"] == 1
    assert "知识问答报告" in q.export_report()["报告"]
    assert q.delete_doc("测试_文档.txt")["ok"] is True
    assert q.stats()["文档数"] == 0


def test_knowledge_import_file_and_indexes(tmp_path, monkeypatch):
    q = _qa(tmp_path)
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")

    monkeypatch.setattr("core.document_parser.parse",
                        lambda _p: {"ok": True, "text": "hello world",
                                    "chars": 11, "metadata": {}})
    monkeypatch.setattr("core.document_parser.chunk_text",
                        lambda _t: [{"id": "0", "text": "hello"}])
    monkeypatch.setattr("core.retrieval.HybridRetriever", _FakeIndex)
    monkeypatch.setattr("core.fts_index.FTSIndex", _FakeIndex)
    r = q.import_file(str(src))
    assert r["ok"] is True
    assert os.path.exists(r["文件"])


def test_knowledge_search_sources_and_rebuild(tmp_path, monkeypatch):
    q = _qa(tmp_path)
    q.add_doc("a", "alpha")
    monkeypatch.setattr("core.retrieval.HybridRetriever", _FakeIndex)
    monkeypatch.setattr("core.fts_index.FTSIndex", _FakeIndex)
    monkeypatch.setattr("modules.installed.knowledge_qa.chunk_text",
                        lambda _t: [{"id": "0", "text": "alpha"}])
    hits = q.search_sources("alpha")
    assert hits
    assert q.rebuild_index()["ok"] is True


def test_knowledge_ask_and_clear(tmp_path):
    q = _qa(tmp_path)
    q.add_doc("a", "Python 知识")
    r = q.ask("Python")
    assert r["回答"] == "知识库回答"
    assert r["参考文档"]
    assert q.clear_all()["ok"] is True
    assert q.stats()["文档数"] == 0