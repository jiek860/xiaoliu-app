# -*- coding: utf-8 -*-
"""工作区索引：文件、Python 符号、import、测试关联。

Sprint 3 基础模块。只使用标准库，不依赖 Qt，便于测试和后台重建。
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".bat", ".ps1", ".sql", ".sh", ".xml",
}
SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", "libs", "optional_libs", "backups", "staging",
    "dist", "build", ".venv", "venv", "browsers", "data",
}
MAX_FILE_BYTES = 2 * 1024 * 1024


def _sha1(path):
    h = hashlib.sha1(usedforsecurity=False)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _rel(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


class WorkspaceIndex:
    def __init__(self, base: str, workspace_root: str = ""):
        self.base = base
        self.root = os.path.abspath(workspace_root or base)
        key = hashlib.sha1(self.root.lower().encode("utf-8"),
                                  usedforsecurity=False).hexdigest()[:12]
        self.dir = os.path.join(base, "data", "workspace_index", key)
        self.path = os.path.join(self.dir, "index.json")
        self.data = {
            "version": 1,
            "root": self.root,
            "updated_at": 0,
            "files": {},
            "symbols": {},
            "imports": {},
            "tests": [],
        }
        self.load()

    # ---------- 持久化 ----------
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("root") == self.root:
                self.data.update(d)
        except (OSError, ValueError):
            pass
        return self.data

    def save(self):
        self.data["updated_at"] = time.time()
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        return self.path

    # ---------- 构建 ----------
    def rebuild(self, max_files=20000):
        files, symbols, imports, tests = {}, {}, {}, []
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if count >= max_files:
                    break
                p = os.path.join(dirpath, name)
                rel = _rel(self.root, p)
                try:
                    stat = os.stat(p)
                except OSError:
                    continue
                if stat.st_size > MAX_FILE_BYTES:
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in TEXT_EXT:
                    continue
                entry = {
                    "path": rel, "ext": ext, "size": stat.st_size,
                    "mtime": stat.st_mtime, "sha1": _sha1(p),
                }
                if ext == ".py":
                    py = self._analyze_python(p, rel)
                    entry.update(py["meta"])
                    for sym in py["symbols"]:
                        symbols.setdefault(sym["name"], []).append(sym)
                    if py["imports"]:
                        imports[rel] = py["imports"]
                    if self._looks_like_test(rel):
                        tests.append(rel)
                files[rel] = entry
                count += 1
        self.data.update({"files": files, "symbols": symbols,
                          "imports": imports, "tests": sorted(set(tests)),
                          "updated_at": time.time(), "root": self.root})
        self.save()
        return self.stats()

    def refresh(self, max_files=20000):
        """增量刷新：只分析新增/变更文件，未变化文件复用旧索引。"""
        old_files = dict(self.data.get("files") or {})
        old_symbols = dict(self.data.get("symbols") or {})
        old_imports = dict(self.data.get("imports") or {})
        old_tests = set(self.data.get("tests") or [])
        files, changed = {}, set()
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                if count >= max_files:
                    break
                p = os.path.join(dirpath, name)
                rel = _rel(self.root, p)
                try:
                    stat = os.stat(p)
                except OSError:
                    continue
                if stat.st_size > MAX_FILE_BYTES:
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in TEXT_EXT:
                    continue
                old = old_files.get(rel)
                if old and old.get("mtime") == stat.st_mtime and                         old.get("size") == stat.st_size and old.get("sha1"):
                    files[rel] = old
                else:
                    entry = {"path": rel, "ext": ext, "size": stat.st_size,
                             "mtime": stat.st_mtime, "sha1": _sha1(p)}
                    if ext == ".py":
                        py = self._analyze_python(p, rel)
                        entry.update(py["meta"])
                        entry["_symbols"] = py["symbols"]
                        entry["_imports"] = py["imports"]
                    files[rel] = entry
                    changed.add(rel)
                count += 1
            if count >= max_files:
                break

        # 未变化文件的符号/import 从旧索引复用；变化文件只取新分析结果。
        unchanged = set(files) - changed
        symbols, imports, tests = {}, {}, []
        for sym_name, vals in old_symbols.items():
            kept = [v for v in vals if v.get("file") in unchanged]
            if kept:
                symbols[sym_name] = kept
        for rel in unchanged:
            if rel in old_imports:
                imports[rel] = old_imports[rel]
            if rel in old_tests:
                tests.append(rel)
        for rel in changed:
            entry = files[rel]
            for sym in entry.pop("_symbols", []) or []:
                symbols.setdefault(sym["name"], []).append(sym)
            imps = entry.pop("_imports", []) or []
            if imps:
                imports[rel] = imps
            if self._looks_like_test(rel):
                tests.append(rel)
        self.data.update({"files": files, "symbols": symbols,
                          "imports": imports, "tests": sorted(set(tests)),
                          "updated_at": time.time(), "root": self.root})
        self.save()
        out = self.stats()
        out["changed"] = sorted(changed)
        out["removed"] = sorted(set(old_files) - set(files))
        return out

    def update_file(self, path):
        p = path if os.path.isabs(path) else os.path.join(self.root, path)
        rel = _rel(self.root, p)
        if not os.path.isfile(p):
            self.data.get("files", {}).pop(rel, None)
            return self.stats()
        try:
            stat = os.stat(p)
        except OSError:
            return self.stats()
        ext = os.path.splitext(p)[1].lower()
        entry = {"path": rel, "ext": ext, "size": stat.st_size,
                 "mtime": stat.st_mtime, "sha1": _sha1(p)}
        if ext == ".py":
            py = self._analyze_python(p, rel)
            entry.update(py["meta"])
            # 清掉这个文件的旧符号
            for name in list(self.data.get("symbols", {})):
                vals = [s for s in self.data["symbols"][name]
                        if s.get("file") != rel]
                if vals:
                    self.data["symbols"][name] = vals
                else:
                    self.data["symbols"].pop(name, None)
            for sym in py["symbols"]:
                self.data.setdefault("symbols", {}).setdefault(
                    sym["name"], []).append(sym)
            if py["imports"]:
                self.data.setdefault("imports", {})[rel] = py["imports"]
            else:
                self.data.get("imports", {}).pop(rel, None)
            tests = set(self.data.get("tests") or [])
            if self._looks_like_test(rel):
                tests.add(rel)
            else:
                tests.discard(rel)
            self.data["tests"] = sorted(tests)
        self.data.setdefault("files", {})[rel] = entry
        self.save()
        return self.stats()

    def _analyze_python(self, path, rel):
        meta = {"language": "python", "classes": 0, "functions": 0,
                "syntax_error": ""}
        symbols, imports = [], []
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
            tree = ast.parse(src)
        except SyntaxError as e:
            meta["syntax_error"] = "line %s: %s" % (e.lineno, e.msg)
            return {"meta": meta, "symbols": [], "imports": []}
        except OSError:
            return {"meta": meta, "symbols": [], "imports": []}

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                meta["functions"] += 1
                symbols.append({
                    "name": node.name, "kind": "function", "file": rel,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                })
            elif isinstance(node, ast.ClassDef):
                meta["classes"] += 1
                symbols.append({
                    "name": node.name, "kind": "class", "file": rel,
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                })
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        meta["functions"] += 1
                        symbols.append({
                            "name": "%s.%s" % (node.name, child.name),
                            "kind": "method", "file": rel,
                            "line": child.lineno,
                            "end_line": getattr(child, "end_lineno", child.lineno),
                        })
            elif isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                imports.extend("%s.%s" % (mod, a.name) for a in node.names)
        return {"meta": meta, "symbols": symbols,
                "imports": sorted(set(imports))}

    @staticmethod
    def _looks_like_test(rel):
        name = os.path.basename(rel).lower()
        return (name.startswith("test_") or name.endswith("_test.py")
                or "/tests/" in "/" + rel.lower())

    # ---------- 查询 ----------
    def stats(self):
        files = self.data.get("files") or {}
        return {
            "root": self.root,
            "files": len(files),
            "symbols": len(self.data.get("symbols") or {}),
            "tests": len(self.data.get("tests") or []),
            "updated_at": self.data.get("updated_at", 0),
        }

    def find_symbols(self, name, limit=50):
        q = str(name or "").lower()
        out = []
        for sym_name, vals in (self.data.get("symbols") or {}).items():
            if q in sym_name.lower():
                out.extend(vals)
                if len(out) >= limit:
                    break
        return out[:limit]

    def related_tests(self, rel_path):
        rel = str(rel_path).replace("\\", "/")
        stem = os.path.splitext(os.path.basename(rel))[0]
        related = []
        for test in self.data.get("tests") or []:
            test_name = os.path.basename(test).lower()
            if stem.lower() in test_name or test_name.startswith("test_"):
                # 只有在测试内容引用模块名时才算强关联
                try:
                    p = os.path.join(self.root, test)
                    src = open(p, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                if stem in src or ("import " + stem) in src:
                    related.append(test)
        return related

    def search_text(self, query, max_hits=100):
        q = str(query or "")
        if not q:
            return []
        try:
            pat = re.compile(q, re.I)
        except re.error:
            pat = re.compile(re.escape(q), re.I)
        hits = []
        for rel in sorted((self.data.get("files") or {}).keys()):
            if len(hits) >= max_hits:
                break
            p = os.path.join(self.root, rel)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if pat.search(line):
                            hits.append({"file": rel, "line": i,
                                         "text": line.strip()[:200]})
                            if len(hits) >= max_hits:
                                break
            except OSError:
                continue
        return hits

    def imports_of(self, rel_path):
        rel = str(rel_path).replace("\\", "/")
        return list((self.data.get("imports") or {}).get(rel) or [])

    def recent_files(self, limit=20):
        files = list((self.data.get("files") or {}).values())
        files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        return files[:limit]
