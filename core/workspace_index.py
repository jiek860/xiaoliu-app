# -*- coding: utf-8 -*-
"""工作区索引：文件、Python 符号、import、测试关联。

Sprint 3 基础模块。只使用标准库，不依赖 Qt，便于测试和后台重建。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from core.symbol_parser import parse_source, ts_available

TEXT_EXT = {
    ".py", ".md", ".txt", ".json", ".js", ".ts", ".tsx", ".jsx",
    ".mjs", ".cjs",
    ".html", ".css", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".bat", ".ps1", ".sql", ".sh", ".xml",
}
SYMBOL_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
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


def module_name(rel):
    """相对路径 → 模块名（``core/lsp_client.py`` → ``core.lsp_client``）。"""
    text = str(rel or "").replace("\\", "/").strip("/")
    if not text:
        return ""
    if text.endswith(".py"):
        text = text[:-3]
    else:
        text = os.path.splitext(text)[0]
    parts = [p for p in text.split("/") if p and p != "__init__"]
    return ".".join(parts)


class WorkspaceIndex:
    def __init__(self, base: str, workspace_root: str = ""):
        self.base = base
        self.root = os.path.abspath(workspace_root or base)
        key = hashlib.sha1(self.root.lower().encode("utf-8"),
                                  usedforsecurity=False).hexdigest()[:12]
        self.dir = os.path.join(base, "data", "workspace_index", key)
        self.path = os.path.join(self.dir, "index.json")
        self.data = {
            "version": 2,
            "root": self.root,
            "updated_at": 0,
            "files": {},
            "symbols": {},
            "imports": {},
            "tests": [],
        }
        self._ref_cache = {}      # 名字 → 引用点（第 8 批；索引一变就清空）
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
        cache = getattr(self, "_ref_cache", None)
        if cache is not None:     # 引用缓存跟着索引一起失效
            cache.clear()
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
                if ext in SYMBOL_EXT:
                    py = parse_source(p, rel)
                    entry.update(py["meta"])
                    for sym in py["symbols"]:
                        symbols.setdefault(sym["name"], []).append(sym)
                    if py["imports"]:
                        imports[rel] = py["imports"]
                if ext == ".py" and self._looks_like_test(rel):
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
                    if ext in SYMBOL_EXT:
                        py = parse_source(p, rel)
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
        if ext in SYMBOL_EXT:
            py = parse_source(p, rel)
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
        """兼容旧调用：真正的解析在 core.symbol_parser。"""
        return parse_source(path, rel)

    @staticmethod
    def _looks_like_test(rel):
        name = os.path.basename(rel).lower()
        return (name.startswith("test_") or name.endswith("_test.py")
                or "/tests/" in "/" + rel.lower())

    # ---------- 查询 ----------
    def stats(self):
        files = self.data.get("files") or {}
        engines = {}
        for vals in (self.data.get("symbols") or {}).values():
            for s in vals:
                key = str(s.get("engine") or "unknown")
                engines[key] = engines.get(key, 0) + 1
        return {
            "root": self.root,
            "files": len(files),
            "symbols": len(self.data.get("symbols") or {}),
            "tests": len(self.data.get("tests") or []),
            "symbol_engines": engines,
            "tree_sitter": ts_available(),
            "updated_at": self.data.get("updated_at", 0),
        }

    def find_symbols(self, name, limit=50, kind=None, file=None):
        """符号检索：精确 > 限定名后缀 > 前缀 > 子串；可按类型/文件过滤。

        之前是"字典键子串包含"，`main` 会先命中 `domain` 之类。现在按匹配
        强度排序，并带上解析引擎与置信度，调用方能区分 AST 与正则结果。
        """
        q = str(name or "").strip()
        ql = q.lower()
        want_kind = str(kind or "").strip().lower()
        want_file = str(file or "").replace("\\", "/").strip().lower()
        scored = []
        for sym_name, vals in (self.data.get("symbols") or {}).items():
            nl = sym_name.lower()
            if not ql:
                score = 9
            elif nl == ql:
                score = 0
            elif nl.endswith("." + ql):
                score = 1
            elif nl.startswith(ql):
                score = 2
            elif ql in nl:
                score = 3
            elif any(part == ql for part in re.split(r"[._]", nl)):
                score = 2
            else:
                continue
            for s in vals:
                if want_kind and str(s.get("kind") or "").lower() != want_kind:
                    continue
                if want_file and want_file not in str(
                        s.get("file") or "").replace("\\", "/").lower():
                    continue
                scored.append((score, s))
        scored.sort(key=lambda x: (
            x[0], str(x[1].get("file") or ""), int(x[1].get("line") or 0)))
        return [s for _score, s in scored[:max(1, int(limit or 1))]]

    def related_tests(self, rel_path, deep=False):
        rel = str(rel_path).replace("\\", "/")
        stem = os.path.splitext(os.path.basename(rel))[0]
        related, weak = [], []
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
                elif deep and stem.lower() in test_name:
                    # 深度⑥：只靠文件名对上的也算候选（排在强关联之后）
                    weak.append(test)
        if deep:
            return related + [t for t in weak if t not in related]
        return related

    # ---------- 第 8 批：引用 / 相关符号 / 仓库地图 / 测试关联 ----------
    def importers_of(self, rel_path):
        """哪些文件 import 了这个文件（一次遍历 imports 表，O(总 import 数)）。"""
        module = module_name(rel_path)
        if not module:
            return []
        out = []
        for src, imports in (self.data.get("imports") or {}).items():
            if src == rel_path:
                continue
            for imp in imports or []:
                text = str(imp)
                if text == module or text.startswith(module + "."):
                    out.append(src)
                    break
        return out

    def _symbol_enclosing(self, rel, line):
        """某一行落在哪个符号里（按 line/end_line 区间，取最内层）。"""
        best, best_start = "", -1
        for name, vals in (self.data.get("symbols") or {}).items():
            for item in vals or []:
                if item.get("file") != rel:
                    continue
                try:
                    start = int(item.get("line") or 0)
                    end = int(item.get("end_line") or start)
                except (TypeError, ValueError):
                    continue
                if start <= int(line) <= max(start, end) and start > best_start:
                    best_start = start
                    best = str(item.get("name") or name)
        return best

    def references_of(self, name, limit=40, max_files=400):
        """按名字找跨文件引用点（定义行不算）；结果按"最近改动的文件优先"。

        纯文本扫描有上限（默认最多 400 个文件），够用且不会因为仓库大而卡死；
        同一个名字的结果在索引不变期间缓存，连续问同一个符号不会重复读盘。
        """
        key = str(name or "").strip()
        if not key:
            return []
        cached = self._ref_cache.get(key)
        if cached is not None:
            return [dict(x) for x in cached]
        word = re.escape(key.rsplit(".", 1)[-1])
        try:
            pat = re.compile(r"\b%s\b" % word)
            def_pat = re.compile(r"^\s*(?:async\s+def|def|class)\s+%s\b" % word)
        except re.error:
            return []
        files = list((self.data.get("files") or {}).values())
        files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
        out, scanned = [], 0
        for entry in files:
            if scanned >= max(1, int(max_files)) or len(out) >= limit:
                break
            rel = str(entry.get("path") or "")
            if str(entry.get("ext") or "") not in SYMBOL_EXT:
                continue
            scanned += 1
            try:
                with open(os.path.join(self.root, rel.replace("/", os.sep)),
                          encoding="utf-8", errors="replace") as fp:
                    lines = fp.read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if not pat.search(line) or def_pat.match(line):
                    continue
                out.append({"file": rel, "line": i, "text": line.strip()[:160]})
                if len(out) >= limit:
                    break
        self._ref_cache[key] = out[:limit]
        return [dict(x) for x in self._ref_cache[key]]

    def related_symbols(self, rel_path, symbol="", limit=8):
        """与给定文件/符号相关的符号（B2 基础，供上下文注入）。

        四路来源按优先级排列：同文件邻居 > 引用本文件/本符号的地方 >
        本文件 import 的模块里的同名符号。每条都带 ``reason``，方便
        Agent 提示词里写"为什么给你看这段"。
        """
        rel = str(rel_path or "").replace("\\", "/")
        want = str(symbol or "").strip()
        out, seen = [], set()

        def add(item, reason, weight):
            path = str(item.get("file") or "")
            name = str(item.get("name") or "")
            line = int(item.get("line") or 0)
            key = (path, name, line)
            if not name or key in seen or (path == rel and name == want):
                return
            seen.add(key)
            out.append({"file": path, "name": name,
                        "kind": item.get("kind") or "", "line": line,
                        "end_line": int(item.get("end_line") or line),
                        "reason": reason, "weight": weight})

        for _name, vals in (self.data.get("symbols") or {}).items():
            for item in vals or []:
                if item.get("file") == rel:
                    add(item, "同文件", 5)
        if want:
            for hit in self.references_of(want, limit=20):
                owner = self._symbol_enclosing(hit["file"], hit["line"])
                if owner:
                    for item in (self.data.get("symbols") or {}).get(owner, []):
                        if item.get("file") == hit["file"]:
                            add(item, "引用了 %s" % want, 4)
        for src in self.importers_of(rel)[:6]:
            for _name, vals in (self.data.get("symbols") or {}).items():
                for item in vals or []:
                    if item.get("file") == src and \
                            str(item.get("kind")) in ("class", "function"):
                        add(item, "引用了本文件", 3)
        for imp in self.imports_of(rel):
            mod_rel = str(imp).replace(".", "/") + ".py"
            if mod_rel not in (self.data.get("files") or {}):
                continue
            leaf = str(imp).rsplit(".", 1)[-1]
            for item in (self.data.get("symbols") or {}).get(leaf, []):
                if item.get("file") == mod_rel:
                    add(item, "本文件引用了它", 2)
        out.sort(key=lambda x: (-int(x.get("weight") or 0),
                               str(x.get("file") or ""), int(x.get("line") or 0)))
        return out[:max(1, int(limit or 1))]

    def _heat_map(self):
        """模块被 import 的次数（含包路径前缀），一次遍历算出。"""
        heat = {}
        for _src, imports in (self.data.get("imports") or {}).items():
            for imp in imports or []:
                parts = str(imp).split(".")
                for i in range(len(parts), 0, -1):
                    mod = ".".join(parts[:i])
                    heat[mod] = heat.get(mod, 0) + 1
        return heat

    def repo_map(self, max_chars=2400, max_files=40, per_file=6):
        """按引用热度排序的项目符号地图（深度⑤，aider 风格但更省）。

        "热度"= 有多少文件 import 了这个模块（``_heat_map`` 一次算完）。
        每行形如 ``core/lsp_client.py (被 3 处引用): LspClient, server_for``，
        超出字数预算就截断并留一句提示，绝不超预算。
        """
        heat = self._heat_map()
        by_file = {}
        for name, vals in (self.data.get("symbols") or {}).items():
            for item in vals or []:
                if str(item.get("kind")) not in ("class", "function"):
                    continue
                by_file.setdefault(str(item.get("file") or ""), []).append(
                    (int(item.get("line") or 0), name))
        rows = []
        for rel, entry in (self.data.get("files") or {}).items():
            if str(entry.get("ext") or "") not in SYMBOL_EXT:
                continue
            if not by_file.get(rel):
                continue
            rows.append((int(heat.get(module_name(rel), 0)), rel))
        rows.sort(key=lambda x: (-x[0], x[1]))
        lines, used, shown_files = [], 0, 0
        for score, rel in rows:
            if shown_files >= max(1, int(max_files)):
                break
            names = sorted(by_file.get(rel) or [])
            picked = [n for _line, n in names[:max(1, int(per_file))]]
            more = "" if len(names) <= len(picked) else " …(+%d)" % (
                len(names) - len(picked))
            line = "%s (被 %d 处引用): %s%s" % (
                rel, score, ", ".join(picked), more)
            if used + len(line) > max(0, int(max_chars)) - 20:
                lines.append("…（地图已到字数上限，用 grep/find_symbols 继续）")
                break
            lines.append(line)
            used += len(line) + 1
            shown_files += 1
        return "\n".join(lines)

    def tests_for(self, rel_path):
        """改动文件 → 建议先跑的测试（深度⑥：名字对上就算候选）。"""
        return self.related_tests(rel_path, deep=True)

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
