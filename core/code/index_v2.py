# -*- coding: utf-8 -*-
"""代码索引 v2（批次 45.1/45.2）：函数级分块 + FTS5 + 增量 + 调用图。

设计取舍：
    · 独立的 ``data/code_index_v2.db``，不碰知识库的 ``retrieval.db``，
      避免两套 schema 互相迁移；
    · 分块以 Python AST 为准（函数/类），非 Python 或解析失败退化为整文件；
    · 增量靠 ``meta(path, mtime, size, hash)``：mtime+size 相同直接跳过，
      变了才重读重算 hash；删除的文件顺手清掉；
    · 单文件 >2MB 跳过（生成物/压缩包不值得进索引）；
    · 调用图与 import 反查存在同一库的普通表，刷新时按 path 覆盖；
    · SQLite 不可用或 FTS5 缺失时 ``ok=False``，所有查询返回空，不抛异常。
"""
from __future__ import annotations

import ast
import hashlib
import os
import sqlite3
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             "modules_repo", "dist", "build", ".pytest_cache", "data",
             "optional_libs", "backups", "updates", "staging"}
PY_EXT = ".py"
CHUNK_MAX_CHARS = 8000


def _hash_text(text):
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _walk_files(root, max_files):
    files = []
    for dirpath, dirnames, filenames in os.walk(str(root or ".")):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(PY_EXT):
                files.append(os.path.relpath(
                    os.path.join(dirpath, name),
                    root).replace("\\", "/"))
                if len(files) >= max_files:
                    return files
    return files


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _parse_python(text, rel):
    """返回 (chunks, calls, imports)；解析失败返回 ([], [], [])。"""
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        fallback = [{"symbol": os.path.splitext(os.path.basename(rel))[0],
                     "kind": "module", "start_line": 1,
                     "end_line": max(1, len(lines)),
                     "text": text[:CHUNK_MAX_CHARS]}]
        return fallback, [], []
    chunks, calls, imports = [], [], []

    def add_chunk(node):
        start = int(getattr(node, "lineno", 1) or 1)
        end = int(getattr(node, "end_lineno", start) or start)
        body = "\n".join(lines[start - 1:end])[:CHUNK_MAX_CHARS]
        chunks.append({"symbol": node.name,
                       "kind": "class" if isinstance(node, ast.ClassDef)
                       else "function",
                       "start_line": start, "end_line": end, "text": body})

    def walk(node, caller):
        for child in ast.iter_child_nodes(node):
            name = caller
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                add_chunk(child)
                name = child.name
            if isinstance(child, ast.Call):
                target = _call_name(child.func)
                if target:
                    calls.append({"caller": caller or "<module>",
                                  "callee": target,
                                  "line": int(getattr(child, "lineno", 1))})
            walk(child, name)

    walk(tree, "")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    if not chunks:
        body = text[:CHUNK_MAX_CHARS]
        chunks.append({"symbol": os.path.splitext(os.path.basename(rel))[0],
                       "kind": "module", "start_line": 1,
                       "end_line": max(1, len(lines)), "text": body})
    return chunks, calls, imports


class CodeIndexV2:
    """仓库级代码索引；``ok=False`` 时全部查询安全返回空。"""

    def __init__(self, base, root=None):
        self.base = str(base or ".")
        self.root = str(root or self.base)
        self.path = os.path.join(self.base, "data", "code_index_v2.db")
        self.ok = False
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with self._conn() as conn:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS code_chunks USING fts5("
                    "text, path UNINDEXED, symbol UNINDEXED, kind UNINDEXED, "
                    "start_line UNINDEXED, end_line UNINDEXED)")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS meta(path TEXT PRIMARY KEY, "
                    "mtime REAL, size INTEGER, hash TEXT, updated_at REAL)")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS calls(caller TEXT, callee TEXT, "
                    "path TEXT, line INTEGER)")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS imports(path TEXT, module TEXT)")
            self.ok = True
        except Exception as e:
            _x6_swallowed(__name__, e, "init")

    def _drop_file(self, conn, rel):
        conn.execute("DELETE FROM code_chunks WHERE path = ?", (rel,))
        conn.execute("DELETE FROM calls WHERE path = ?", (rel,))
        conn.execute("DELETE FROM imports WHERE path = ?", (rel,))
        conn.execute("DELETE FROM meta WHERE path = ?", (rel,))

    def _add_file(self, conn, root, rel):
        full = os.path.join(root, rel.replace("/", os.sep))
        size = os.path.getsize(full)
        if size > MAX_FILE_BYTES:
            return 0
        with open(full, encoding="utf-8", errors="replace") as fp:
            text = fp.read()
        digest = _hash_text(text)
        chunks, calls, imports = _parse_python(text, rel)
        self._drop_file(conn, rel)
        for chunk in chunks:
            conn.execute(
                "INSERT INTO code_chunks(text, path, symbol, kind, start_line, "
                "end_line) VALUES (?, ?, ?, ?, ?, ?)",
                (chunk["text"], rel, chunk["symbol"], chunk["kind"],
                 str(chunk["start_line"]), str(chunk["end_line"])))
        for call in calls:
            conn.execute(
                "INSERT INTO calls(caller, callee, path, line) VALUES (?,?,?,?)",
                (call["caller"], call["callee"], rel, call["line"]))
        for module in sorted(set(imports)):
            conn.execute("INSERT INTO imports(path, module) VALUES (?, ?)",
                         (rel, module))
        conn.execute(
            "INSERT OR REPLACE INTO meta(path, mtime, size, hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rel, os.path.getmtime(full), size, digest, time.time()))
        return len(chunks)

    def refresh(self, root=None, max_files=2000):
        """增量刷新；返回统计（秒数用于 DoD 观察）。"""
        stats = {"ok": self.ok, "files": 0, "updated": 0, "skipped": 0,
                 "removed": 0, "chunks": 0, "seconds": 0.0}
        if not self.ok:
            return stats
        started = time.time()
        root = str(root or self.root)
        files = _walk_files(root, max_files)
        stats["files"] = len(files)
        try:
            with self._conn() as conn:
                known = {row["path"]: (row["mtime"], row["size"])
                         for row in conn.execute(
                             "SELECT path, mtime, size FROM meta")}
                for rel in files:
                    full = os.path.join(root, rel.replace("/", os.sep))
                    try:
                        mtime = os.path.getmtime(full)
                        size = os.path.getsize(full)
                    except OSError:
                        continue
                    old = known.pop(rel, None)
                    if old and abs(old[0] - mtime) < 1e-6 and old[1] == size:
                        stats["skipped"] += 1
                        continue
                    stats["chunks"] += self._add_file(conn, root, rel)
                    stats["updated"] += 1
                for rel in list(known):
                    self._drop_file(conn, rel)
                    stats["removed"] += 1
        except Exception as e:
            _x6_swallowed(__name__, e, "refresh")
            stats["ok"] = False
        stats["seconds"] = round(time.time() - started, 3)
        return stats

    def search(self, query, top_k=10):
        text = str(query or "").strip()
        if not self.ok or not text:
            return []
        quoted = '"' + text.replace('"', '""') + '"*'
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT text, path, symbol, kind, start_line, end_line, "
                    "bm25(code_chunks) AS score FROM code_chunks "
                    "WHERE code_chunks MATCH ? ORDER BY score LIMIT ?",
                    (quoted, int(top_k))).fetchall()
            return [{"path": r["path"], "symbol": r["symbol"],
                     "kind": r["kind"], "start_line": int(r["start_line"]),
                     "end_line": int(r["end_line"]),
                     "text": r["text"], "score": -float(r["score"] or 0)}
                    for r in rows]
        except Exception as e:
            _x6_swallowed(__name__, e, "search")
            return []

    def outline(self, rel):
        if not self.ok:
            return []
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT symbol, kind, start_line, end_line FROM code_chunks "
                    "WHERE path = ? ORDER BY CAST(start_line AS INTEGER)",
                    (rel,)).fetchall()
            return [{"symbol": r["symbol"], "kind": r["kind"],
                     "start_line": int(r["start_line"]),
                     "end_line": int(r["end_line"])} for r in rows]
        except Exception as e:
            _x6_swallowed(__name__, e, "outline")
            return []

    def callers_of(self, name):
        return self._query_names("SELECT DISTINCT caller FROM calls "
                                "WHERE callee = ?", name)

    def callees_of(self, name):
        return self._query_names("SELECT DISTINCT callee FROM calls "
                                "WHERE caller = ?", name)

    def _query_names(self, sql, name):
        if not self.ok or not str(name or "").strip():
            return []
        try:
            with self._conn() as conn:
                rows = conn.execute(sql, (str(name),)).fetchall()
            return sorted({str(r[0]) for r in rows if r[0]})
        except Exception as e:
            _x6_swallowed(__name__, e, "call graph")
            return []

    def tests_for(self, rel):
        """import 反查：引用了该模块的测试文件。"""
        rel = str(rel or "").replace("\\", "/")
        if not self.ok or not rel.endswith(".py"):
            return []
        module = rel[:-3].replace("/", ".")
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT path FROM imports WHERE module = ? "
                    "OR module LIKE ?", (module, module + ".%")).fetchall()
        except Exception as e:
            _x6_swallowed(__name__, e, "tests_for")
            return []
        out = []
        for row in rows:
            path = str(row["path"])
            base = os.path.basename(path)
            if base.startswith("test_") or path.startswith("tests/"):
                out.append(path)
        return sorted(out)

    def stats(self):
        if not self.ok:
            return {"ok": False, "chunks": 0, "files": 0}
        try:
            with self._conn() as conn:
                chunks = conn.execute(
                    "SELECT COUNT(*) FROM code_chunks").fetchone()[0]
                files = conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
            return {"ok": True, "chunks": int(chunks), "files": int(files)}
        except Exception as e:
            _x6_swallowed(__name__, e, "stats")
            return {"ok": False, "chunks": 0, "files": 0}
