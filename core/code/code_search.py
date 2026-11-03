# -*- coding: utf-8 -*-
"""代码语义检索（第 8 批 深度⑦）：把相关代码片段从向量库里找回来。

为什么复用 ``core/vector_store.py``
----------------------------------
向量库已经处理了「Chroma 可选加速 / SQLite 落盘 / 嵌入失败走关键词降级」
这一整套麻烦事，再写一套只会更差。这里只做两件自己的事：

* 入库时把片段写成**自带坐标**的一行头 ``【代码片段】core/x.py:12``，
  因为 ``VectorStore.search()`` 只回 ``{text, score}``、不带 tag，
  坐标写在正文里才能在召回后还原成 ``文件:行``；
* 召回后按这个头过滤 —— 聊天记忆和代码片段在一个库里，
  不这样过滤就会把代码当记忆、把记忆当代码。

默认 **关**（``代码.语义检索=False``）：代码片段一旦进库，记忆检索也会
搜到它，长片段会把上下文挤爆。用户明确打开后才会入库与召回。
"""
from __future__ import annotations

import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

TAG = "代码"
MARK = "【代码片段】"
CHUNK_LINES = 40
MAX_CHUNKS = 60
_HEAD_RE = re.compile(r"^%s([^\s:]+):(\d+)\s*$" % re.escape(MARK), re.M)


def enabled(trunk):
    """``代码.语义检索`` 开关（默认关，理由见模块注释）。"""
    try:
        value = trunk.rule("代码.语义检索", False)
    except Exception as e:
        _x6_swallowed(__name__, e, "semantic switch")
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "off", "false", "no", "0")
    return bool(value)


def _call(trunk, method, *args, **kwargs):
    """调向量库；拿不到（未加载/异常）返回 None，不抛。"""
    if trunk is None:
        return None
    try:
        return trunk.call("vector_store", method, *args, **kwargs)
    except Exception as e:  # 静默是故意的 - 向量库不可用就当没有语义检索
        _x6_swallowed(__name__, e, "vector store %s" % method)
        return None


def chunk_text(rel, text, size=CHUNK_LINES):
    """把一个文件切成带坐标头的片段：``【代码片段】rel:起始行``。"""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    step = max(10, int(size or CHUNK_LINES))
    out = []
    for start in range(0, len(lines), step):
        seg = lines[start:start + step]
        body = "\n".join(seg).strip()
        if not body:
            continue
        out.append("%s%s:%d\n%s" % (MARK, str(rel).replace("\\", "/"),
                                    start + 1, body))
    return out


def parse_chunk(text):
    """片段头 → {file, line}；不是代码片段返回 None。"""
    match = _HEAD_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return {"file": match.group(1), "line": int(match.group(2))}
    except (TypeError, ValueError):
        return None


def index_code(trunk, root, files=None, max_chunks=MAX_CHUNKS):
    """把文件切片入库（只在开关打开时工作，返回统计，不抛）。

    ⚠️ 现状（2026-11-02 复核）：**这是"代码语义检索"的写半边，目前没有调用方** ——
    `search_code()`（召回）由 `core/code_context.py` 在用，但没有任何地方把代码
    片段写进向量库，所以开关 `代码.语义检索` 打开后也召回不到东西。
    它不是重复实现，删掉会让这个深度⑦能力彻底无处可接，故先保留；
    接线（首次召回时按上限入库）列入后续批次，本批不改运行时行为。
    """
    result = {"ok": False, "indexed": 0, "skipped": 0, "reason": ""}
    if not enabled(trunk):
        result["reason"] = "代码.语义检索=off"
        return result
    targets = list(files or [])
    count = 0
    for rel in targets:
        if count >= max(1, int(max_chunks)):
            break
        path = os.path.join(str(root or "."), str(rel).replace("/", os.sep))
        try:
            with open(path, encoding="utf-8", errors="replace") as fp:
                text = fp.read()
        except OSError:
            result["skipped"] += 1
            continue
        for chunk in chunk_text(rel, text):
            if count >= max(1, int(max_chunks)):
                break
            added = _call(trunk, "add", chunk, tag=TAG)
            count += 1
            if isinstance(added, dict) and added.get("ok"):
                result["indexed"] += 1
            else:
                result["skipped"] += 1
    result["ok"] = result["indexed"] > 0
    if not result["ok"] and not result["reason"]:
        result["reason"] = "没有片段入库（嵌入不可用或文件为空）"
    return result


def search_code(trunk, query, limit=5):
    """语义召回代码片段：只保留带坐标头的片段，坐标还原成 file/line。"""
    if not enabled(trunk) or not str(query or "").strip():
        return []
    rows = _call(trunk, "search", str(query), max(1, int(limit)) * 3)
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        loc = parse_chunk(row.get("text"))
        if not loc:
            continue
        out.append({"file": loc["file"], "line": loc["line"],
                    "score": row.get("score"),
                    "text": str(row.get("text") or "")})
        if len(out) >= max(1, int(limit)):
            break
    return out


def status(trunk=None):
    """自检/设置页用的一句话摘要。"""
    on = enabled(trunk)
    return {"开关": "on" if on else "off", "标签": TAG,
            "摘要": "代码语义检索：%s（开关 代码.语义检索）"
                    % ("开" if on else "关")}
