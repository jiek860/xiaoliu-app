# -*- coding: utf-8 -*-
"""实体解析（批次 44.2）：把意图里的文件/符号/测试/分支落到真实对象。

复用 ``core.workspace_index.WorkspaceIndex``：
    · 文件：精确路径 → 路径后缀 → 同名文件 → 子串，取 ≤5 个候选
    · 符号：``find_symbols`` 精确 > 后缀 > 前缀 > 子串
    · 测试：按 tests 清单匹配文件名
    · 分支：读 ``.git/refs/heads`` 与 ``.git/packed-refs``，不跑子进程

解析不到时不猜：返回 ``ok=False`` + ``candidates``（≤5），交给澄清层。
"""
from __future__ import annotations

import os

from core.workspace_index import SKIP_DIRS, WorkspaceIndex

MAX_CANDIDATES = 5


def build_index(root, base=None, *, rebuild=False, max_files=20000):
    """按需建/加载索引；``rebuild=False`` 时优先用已有索引。"""
    root = os.path.abspath(str(root or "."))
    index = WorkspaceIndex(base or root, workspace_root=root)
    if rebuild or not (index.data.get("files") or {}):
        index.rebuild(max_files=max_files)
    return index


def _norm(value):
    return str(value or "").strip().strip("`'\"").replace("\\", "/")


def _disk_files(root, max_files=20000):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
            and d != "data")
        for name in sorted(filenames):
            found.append(os.path.relpath(
                os.path.join(dirpath, name), root).replace("\\", "/"))
            if len(found) >= max_files:
                return found
    return found


def _all_files(index, root):
    files = index.data.get("files") if index is not None else None
    if isinstance(files, dict) and files:
        return sorted(files.keys())
    return _disk_files(root)


def _file_score(path, query):
    low_path, low_q = path.lower(), query.lower()
    base = os.path.basename(low_path)
    if low_path == low_q:
        return 100
    if low_path.endswith("/" + low_q):
        return 90
    if base == low_q:
        return 80
    if base.startswith(low_q):
        return 60
    if low_q in low_path:
        return 40
    return 0


def _resolve_file(value, files, limit):
    query = _norm(value)
    if not query:
        return {"ok": False, "candidates": []}
    scored = [(s, p) for s, p in
              ((_file_score(p, query), p) for p in files) if s > 0]
    scored.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
    if not scored:
        return {"ok": False, "candidates": []}
    best = scored[0]
    out = {"ok": best[0] >= 80, "path": best[1], "score": best[0],
           "candidates": [p for _s, p in scored[:limit]]}
    if not out["ok"]:
        out["path"] = ""
    return out


def _resolve_symbol(value, index, limit):
    name = _norm(value)
    if not name or index is None:
        return {"ok": False, "symbols": [], "candidates": []}
    hits = index.find_symbols(name, limit=limit)
    if not hits:
        return {"ok": False, "symbols": [], "candidates": []}
    exact = [h for h in hits
             if str(h.get("name") or "").lower() == name.lower()]
    chosen = exact or hits[:1]
    return {"ok": bool(exact), "symbols": chosen,
            "candidates": [h.get("name") for h in hits[:limit]]}


def _resolve_test(value, index, files, limit):
    name = _norm(value)
    if not name:
        return {"ok": False, "candidates": []}
    tests = list((index.data.get("tests") if index is not None else []) or [])
    if not tests:
        tests = [p for p in files if os.path.basename(p).startswith("test_")]
    low = name.lower()
    scored = []
    for path in tests:
        base = os.path.basename(path).lower()
        stem = os.path.splitext(base)[0]
        if stem == low or base == low:
            scored.append((100, path))
        elif low in stem or stem in low:
            scored.append((70, path))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored:
        return {"ok": False, "candidates": [p for p in tests[:limit]]}
    return {"ok": scored[0][0] == 100, "path": scored[0][1],
            "score": scored[0][0],
            "candidates": [p for _s, p in scored[:limit]]}


def branches(root):
    """本地分支名：.git/refs/heads + packed-refs；不是 git 仓库返回 []。"""
    git = os.path.join(str(root or "."), ".git")
    if not os.path.isdir(git):
        return []
    names = []
    heads = os.path.join(git, "refs", "heads")
    for dirpath, _dirs, filenames in os.walk(heads):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, heads).replace("\\", "/")
            names.append(rel)
    packed = os.path.join(git, "packed-refs")
    if os.path.isfile(packed):
        try:
            with open(packed, encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    line = line.strip()
                    if " refs/heads/" in line:
                        names.append(line.split(" refs/heads/", 1)[1])
        except OSError:
            pass
    return sorted(set(n for n in names if n))


def _resolve_branch(value, root, limit):
    name = _norm(value)
    known = branches(root)
    low = name.lower()
    exact = [b for b in known if b.lower() == low]
    fuzzy = [b for b in known if low and low in b.lower() and b not in exact]
    return {"ok": bool(exact),
            "path": exact[0] if exact else "",
            "candidates": (exact + fuzzy)[:limit]}


def resolve_target(target, *, root=".", index=None, files=None, limit=5):
    """解析单个 target；返回 {type, value, ok, ...candidates}。"""
    item = dict(target or {})
    kind = str(item.get("type") or "file").strip().lower()
    value = _norm(item.get("value"))
    files = files if files is not None else _all_files(index, root)
    out = {"type": kind, "value": value, "ok": False, "candidates": []}
    if kind == "file":
        out.update(_resolve_file(value, files, limit))
        out["type"] = "file"
    elif kind == "symbol":
        out.update(_resolve_symbol(value, index, limit))
        out["type"] = "symbol"
    elif kind == "test":
        out.update(_resolve_test(value, index, files, limit))
        out["type"] = "test"
    elif kind == "branch":
        out.update(_resolve_branch(value, root, limit))
        out["type"] = "branch"
    else:
        out["candidates"] = []
    return out


def resolve_targets(targets, *, root=".", index=None, limit=MAX_CANDIDATES):
    files = _all_files(index, root)
    return [resolve_target(t, root=root, index=index, files=files,
                           limit=limit) for t in (targets or [])]


def resolve_text(text, *, root=".", index=None, limit=MAX_CANDIDATES):
    """意图 + 实体一步到位；``resolved`` 为全部 ok，否则给候选。"""
    from core.nl.intent import route
    info = route(text)
    resolved = resolve_targets(info.get("targets"), root=root,
                               index=index, limit=limit)
    info["resolved"] = resolved
    info["entities_ok"] = bool(resolved) and all(r["ok"] for r in resolved)
    info["unresolved"] = [r for r in resolved if not r["ok"]]
    return info
