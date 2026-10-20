# -*- coding: utf-8 -*-
"""SQLite + FTS5 知识块索引；不可用时自动返回空结果。"""
import os
import sqlite3


class FTSIndex:
    def __init__(self, base):
        self.base = base
        self.path = os.path.join(base, "data", "retrieval.db")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.ok = False
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        try:
            with self._conn() as c:
                c.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts "
                    "USING fts5(text, doc_id UNINDEXED, source UNINDEXED, "
                    "page UNINDEXED, heading UNINDEXED)")
            self.ok = True
        except Exception:
            self.ok = False

    def add_many(self, rows):
        if not self.ok:
            return 0
        n = 0
        try:
            with self._conn() as c:
                for r in rows or []:
                    c.execute(
                        "INSERT INTO chunks_fts(text, doc_id, source, page, heading) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (str(r.get("text", "")), str(r.get("doc_id", "")),
                         str(r.get("source", "")), str(r.get("page", "")),
                         str(r.get("heading", ""))))
                    n += 1
            return n
        except Exception:
            return 0

    def clear_all(self):
        if not self.ok:
            return False
        try:
            with self._conn() as c:
                c.execute("DELETE FROM chunks_fts")
            return True
        except Exception:
            return False

    def stats(self):
        if not self.ok:
            return {"ok": False, "count": 0}
        try:
            with self._conn() as c:
                n = c.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
            return {"ok": True, "count": int(n)}
        except Exception:
            return {"ok": False, "count": 0}

    def delete_source(self, source):
        if not self.ok:
            return False
        try:
            with self._conn() as c:
                c.execute("DELETE FROM chunks_fts WHERE source = ?", (source,))
            return True
        except Exception:
            return False

    def search(self, query, top_k=5):
        if not self.ok or not str(query or "").strip():
            return []
        # FTS5 MATCH 语法较严格，用双引号包住用户查询。
        q = '"' + str(query).replace('"', '""') + '"*'
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT text, doc_id, source, page, heading, bm25(chunks_fts) AS score "
                    "FROM chunks_fts WHERE chunks_fts MATCH ? "
                    "ORDER BY score LIMIT ?", (q, int(top_k))).fetchall()
            return [{"text": r["text"], "doc_id": r["doc_id"],
                     "source": r["source"], "page": r["page"],
                     "heading": r["heading"], "score": -float(r["score"] or 0)}
                    for r in rows]
        except Exception:
            return []
