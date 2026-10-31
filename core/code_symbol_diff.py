# -*- coding: utf-8 -*-
"""符号级 diff 与改动影响面（功能深化二期 · C1 工作台）。

工作台（AI 代码 Agent）以前只有「整文件行级 diff」。这里补两件更懂代码的事：

* ``symbols_diff(before, after, ext)``：对比改动前后**符号**（函数/类/方法）
  的增、删、变，给出比纯文本 diff 更可读的结论。
* ``impact_scan(root, name)``：扫仓库里对某个符号名的**文本引用**，
  改动前先看"谁在用"，降低误伤风险。

实现复用 ``core.symbol_parser.parse_source``：把两段文本落到临时文件再解析，
所以 Python 走 ast、JS/TS 走 tree-sitter（可用时），解析口径与追踪一致。
"""
from __future__ import annotations

import os
import tempfile

from core.symbol_parser import parse_source

_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "build", "dist",
              "optional_libs", "data", "logs", "backups"}


def _norm_ext(ext):
    ext = str(ext or ".py").lower()
    return ext if ext.startswith(".") else "." + ext


def _parse_text(text, ext):
    ext = _norm_ext(ext)
    with tempfile.TemporaryDirectory() as d:
        rel = "f" + ext
        p = os.path.join(d, rel)
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(text or ""))
        return parse_source(p, rel)


def symbols_diff(before_text, after_text, ext=".py"):
    """对比两段源码的符号集合，返回 added / removed / changed。"""
    before = _parse_text(before_text, ext)
    after = _parse_text(after_text, ext)
    key = lambda s: (s.get("kind"), s.get("name"))

    b = {key(s): s for s in (before.get("symbols") or [])}
    a = {key(s): s for s in (after.get("symbols") or [])}

    added = [{"name": k[1], "kind": k[0]} for k in a if k not in b]
    removed = [{"name": k[1], "kind": k[0]} for k in b if k not in a]
    changed = []
    for k in a:
        if k not in b:
            continue
        old, new = b[k], a[k]
        if (old.get("line"), old.get("end_line")) != \
                (new.get("line"), new.get("end_line")):
            changed.append({
                "name": k[1], "kind": k[0],
                "before": (old.get("line"), old.get("end_line")),
                "after": (new.get("line"), new.get("end_line")),
            })
    return {"added": added, "removed": removed, "changed": changed}


def impact_scan(root, name, exts=(".py",), max_files=500):
    """扫描 root 下对 name 的文本引用，返回 [{file, line, text}]。"""
    name = str(name or "").strip()
    if not name:
        return []
    exts = tuple(_norm_ext(e) for e in (exts or (".py",)))
    root = os.path.realpath(os.path.abspath(root))
    hits, scanned = [], 0
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in files:
            if not fn.lower().endswith(exts):
                continue
            scanned += 1
            if scanned > int(max_files):
                return hits
            full = os.path.join(dirpath, fn)
            try:
                with open(full, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if name in line:
                            hits.append({
                                "file": os.path.relpath(full, root)
                                          .replace(os.sep, "/"),
                                "line": i, "text": line.strip()[:200],
                            })
                            break   # 一个文件只报第一处，避免刷屏
            except OSError:
                continue
    return hits