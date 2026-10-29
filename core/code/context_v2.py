# -*- coding: utf-8 -*-
"""预算感知上下文 v2（批次 45.3/45.4）。

顺序（固定优先级）：规则 > 目标 > 选区 > 失败栈 > 符号 > 测试 > 片段。
预算按 ``max_chars * 0.75`` 封顶（目标 token -25%），先放高优先级块，
放不下就截断并标记 ``truncated=True``，不会悄悄丢掉规则/失败栈。

失败栈解析支持两种格式：
    File "core/x.py", line 42, in foo
    core/x.py:42:7: error
命中行会映射到最近的符号（函数/类），只注入命中的那一小段。
"""
from __future__ import annotations

import math
import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

TARGET_RATIO = 0.75
MAX_SELECTION = 4000
MAX_RULES = 1200
MAX_GOAL = 1500
MAX_SNIPPET_LINES = 60

_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_CN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_FILE_LINE_RE = re.compile(r'File "([^"]+)", line (\d+)')
_POS_RE = re.compile(r"([A-Za-z]:?[^\s:()\"']+\.py):(\d+)(?::\d+)?")


def estimate_tokens(text):
    """粗估 token：中文 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token。"""
    text = str(text or "")
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return int(cjk + math.ceil(max(0, len(text) - cjk) / 4.0))


def mode(trunk):
    try:
        value = str(trunk.rule("code.context_v2", "shadow")
                    or "shadow").lower()
    except Exception as e:
        _x6_swallowed(__name__, e, "mode")
        return "shadow"
    return value if value in ("off", "shadow", "on") else "shadow"


def goal_terms(goal, limit=12):
    terms = _TERM_RE.findall(str(goal or ""))
    for chunk in _CN_RE.findall(str(goal or "")):
        terms.extend(chunk[i:i + 3] for i in range(0, min(len(chunk), 9), 2))
    out = []
    for term in terms:
        if term.lower() not in ("the", "and", "for", "with", "this", "that") \
                and term not in out:
            out.append(term)
    return out[:limit]


def _rel_path(raw, root):
    value = str(raw or "").strip()
    if not value:
        return ""
    root_abs = os.path.abspath(str(root or "."))
    full = os.path.abspath(value if os.path.isabs(value)
                           else os.path.join(root_abs, value))
    if full.startswith(root_abs):
        return os.path.relpath(full, root_abs).replace("\\", "/")
    return value.replace("\\", "/")


def _symbol_at(index, rel, line):
    if index is None:
        return ""
    for name, items in (index.data.get("symbols") or {}).items():
        for item in items or []:
            if item.get("file") != rel:
                continue
            start = int(item.get("line") or 0)
            end = int(item.get("end_line") or start)
            if start <= int(line) <= max(start, end):
                return str(item.get("name") or name)
    return ""


def _read_lines(root, rel, start, limit):
    path = os.path.join(str(root or "."), rel.replace("/", os.sep))
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            lines = fp.read().splitlines()
    except OSError:
        return ""
    start = max(1, int(start))
    seg = lines[start - 1:start - 1 + int(limit)]
    return "\n".join("%5d| %s" % (start + i, s)
                     for i, s in enumerate(seg))


def parse_failure(text, root=".", index=None, limit=5):
    """从失败输出里抽 file:line，并映射到符号；最多 limit 个。"""
    found, seen = [], set()
    for match in _FILE_LINE_RE.findall(str(text or "")):
        found.append((match[0], int(match[1])))
    for match in _POS_RE.findall(str(text or "")):
        found.append((match[0], int(match[1])))
    out = []
    for raw, line in found:
        rel = _rel_path(raw, root)
        key = (rel, line)
        if not rel or key in seen:
            continue
        seen.add(key)
        out.append({"path": rel, "line": line,
                    "symbol": _symbol_at(index, rel, line)})
        if len(out) >= limit:
            break
    return out


def _failures_block(text, root, index):
    items = parse_failure(text, root, index)
    if not items:
        return "", []
    parts, files = [], []
    for item in items:
        rel, line = item["path"], item["line"]
        symbol = item["symbol"] or "（未定位到符号）"
        snippet = _read_lines(root, rel, max(1, line - 15), 40)
        parts.append("--- %s:%d  %s ---\n%s" % (rel, line, symbol, snippet))
        files.append(rel)
    return "\n\n".join(parts), files


def _file_outline(index, rel, max_items=20):
    if index is None:
        return ""
    lines = []
    for name, items in (index.data.get("symbols") or {}).items():
        for item in items or []:
            if item.get("file") != rel:
                continue
            lines.append("  - %s %s (L%s-L%s)" % (
                item.get("kind"), name, item.get("line"),
                item.get("end_line")))
    return "\n".join(sorted(lines)[:max_items])


def _rank_files(terms, index, max_files):
    scores, hit_lines = {}, {}
    if index is None:
        return [], {}
    for term in terms:
        for hit in index.search_text(term, max_hits=30):
            rel = hit["file"]
            scores[rel] = scores.get(rel, 0) + 3
            hit_lines.setdefault(rel, hit.get("line", 1))
        for sym in index.find_symbols(term, 15):
            rel = sym.get("file")
            if rel:
                scores[rel] = scores.get(rel, 0) + 2
                hit_lines.setdefault(rel, sym.get("line", 1))
    files = sorted(scores, key=lambda x: (-scores[x], x))[:max_files]
    return files, hit_lines


def build(goal, *, root=".", index=None, selection="", open_files=(),
          last_error="", max_files=12, max_chars=24000, rules=None):
    """组装预算内上下文；返回 text/files/tokens/truncated/sections。"""
    budget_chars = int(max(400, int(max_chars) * TARGET_RATIO))
    chunks, used, sections, files_out = [], 0, [], []

    def add(title, body, rels=()):
        nonlocal used
        body = str(body or "").strip()
        if not body:
            return True
        block = "=== %s ===\n%s\n\n" % (title, body)
        if used + len(block) > budget_chars:
            return False
        chunks.append(block)
        used += len(block)
        sections.append(title)
        for rel in rels:
            if rel and rel not in files_out:
                files_out.append(rel)
        return True

    if rules:
        add("PROJECT RULES", str(rules)[:MAX_RULES])
    add("TASK", str(goal or "")[:MAX_GOAL])
    if str(selection or "").strip():
        add("USER SELECTION", str(selection)[:MAX_SELECTION])
    truncated = False
    fail_body, fail_files = _failures_block(last_error, root, index)
    if fail_body:
        add("FAILURE STACK（只注入命中片段）", fail_body, fail_files)
    for rel in list(open_files or [])[:3]:
        rel = _rel_path(rel, root)
        outline = _file_outline(index, rel)
        snippet = _read_lines(root, rel, 1, MAX_SNIPPET_LINES)
        body = ("OUTLINE:\n%s\n" % outline if outline else "") + snippet
        add("OPEN FILE: %s" % rel, body, [rel])
    search_files, hit_lines = _rank_files(goal_terms(goal), index, max_files)
    for rel in search_files:
        if rel in files_out:
            continue
        line = int(hit_lines.get(rel) or 1)
        snippet = _read_lines(root, rel, max(1, line - 20),
                             MAX_SNIPPET_LINES)
        outline = _file_outline(index, rel)
        body = ("OUTLINE:\n%s\n" % outline if outline else "") + snippet
        if not add("FILE: %s" % rel, body, [rel]):
            truncated = True
            break
    tests = []
    if index is not None:
        for rel in search_files[:5]:
            for test in index.related_tests(rel)[:2]:
                if test not in tests:
                    tests.append(test)
    if tests:
        add("RELATED TESTS", "\n".join(tests[:10]), tests[:5])
    text = "".join(chunks)
    return {"text": text, "files": files_out, "symbols": [],
            "tokens": estimate_tokens(text), "budget_chars": budget_chars,
            "truncated": truncated, "sections": sections}
