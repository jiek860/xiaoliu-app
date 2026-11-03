# -*- coding: utf-8 -*-
"""LSP 协议层：帧编解码、位置换算、结果归一、文本编辑落盘。

这一层是**纯函数**（除了 apply_workspace_edit 要读写文件），不碰进程、
不 import Qt，所以能单测；进程与请求流程在 `core/lsp_client.py`。

为什么单独拆出来
----------------
`core/lsp_client.py` 要装下"子进程 + 请求/通知 + 文档同步 + 7 种能力"，
再加协议细节就过 600 行硬上限（tools/check_file_sizes.py 会让它失败）。
协议层本身没有状态，拆开后两边都清爽，测试也更好写。
"""
from __future__ import annotations

import json
import os

HEADER_SEP = b"\r\n\r\n"


def encode_message(obj):
    """dict → LSP 帧（Content-Length 头 + UTF-8 JSON 体）。"""
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return (b"Content-Length: " + str(len(body)).encode("ascii")
            + HEADER_SEP + body)


def decode_message(buf):
    """缓冲区里切一条消息：返回 (obj, rest)；不够一条时返回 (None, buf)。

    ``obj`` 也可能是 None（头部完整但 JSON 坏了）—— 这时 rest 已经前移，
    调用方继续读下一条即可，不要原地卡死。
    """
    if HEADER_SEP not in buf:
        return None, buf
    head, rest = buf.split(HEADER_SEP, 1)
    length = -1
    for line in head.split(b"\r\n"):
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"content-length":
            try:
                length = int(value.strip())
            except ValueError:
                length = -1
    if length < 0 or len(rest) < length:
        return None, buf
    body, rest = rest[:length], rest[length:]
    try:
        return json.loads(body.decode("utf-8", "replace")), rest
    except ValueError:
        return None, rest


def uri_for_path(path):
    """绝对路径 → file:// URI（Windows 反斜杠要转正斜杠）。"""
    from urllib.parse import quote
    p = os.path.abspath(str(path or "")).replace("\\", "/")
    return "file://" + quote(p, safe="/:")


def path_for_uri(uri):
    """file:// URI → 本地路径（不做存在性检查）。"""
    from urllib.parse import unquote
    raw = str(uri or "")
    if raw.startswith("file://"):
        raw = raw[len("file://"):]
    raw = unquote(raw)
    if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and \
            raw[2] == ":":
        raw = raw[1:]
    return os.path.normpath(raw) if raw else ""


def offset_to_position(text, offset):
    """字符偏移（0 基）→ LSP 位置（行/列都 0 基）。"""
    text = text or ""
    off = max(0, min(int(offset or 0), len(text)))
    prefix = text[:off]
    line = prefix.count("\n")
    col = off - (prefix.rfind("\n") + 1)
    return {"line": line, "character": col}


def position_to_offset(text, position):
    """LSP 位置 → 字符偏移；越界夹紧到最后。"""
    text = text or ""
    lines = text.split("\n")
    line = max(0, int((position or {}).get("line") or 0))
    char = max(0, int((position or {}).get("character") or 0))
    if line >= len(lines):
        return len(text)
    base = sum(len(x) + 1 for x in lines[:line])
    return base + min(char, len(lines[line]))


def incremental_change(old, new):
    """老文本 → 新文本 的最小单段改动（didChange 的增量 payload）。

    只发"前后缀之外的那一段"：一次按键就是一处小 range，而不是把整篇
    100KB 的文件重发一遍（深度②）。文本没变返回 None（调用方就不发通知）。
    """
    old = old or ""
    new = new or ""
    if old == new:
        return None
    limit = min(len(old), len(new))
    pre = 0
    while pre < limit and old[pre] == new[pre]:
        pre += 1
    suf = 0
    while suf < limit - pre and old[len(old) - 1 - suf] == \
            new[len(new) - 1 - suf]:
        suf += 1
    start = offset_to_position(old, pre)
    end = offset_to_position(old, len(old) - suf)
    return {
        "range": {"start": start, "end": end},
        "rangeLength": (position_to_offset(old, end)
                        - position_to_offset(old, start)),
        "text": new[pre:len(new) - suf],
    }


def locations_of(result):
    """definition/references 结果归一成 [{path, line, col}]（行列 1 基）。"""
    items = result if isinstance(result, list) else (
        [result] if isinstance(result, dict) else [])
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri") or ""
        rng = (item.get("range") or item.get("targetSelectionRange")
               or item.get("targetRange") or {})
        start = rng.get("start") or {}
        path = path_for_uri(uri)
        if not path:
            continue
        out.append({"path": path,
                    "line": int(start.get("line") or 0) + 1,
                    "col": int(start.get("character") or 0) + 1})
    return out


def hover_text(result):
    """hover 结果 → 纯文本（markdown / MarkedString / MarkupContent 都吃）。"""
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, str):
        return contents.strip()
    if isinstance(contents, dict):
        return str(contents.get("value") or "").strip()
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("value") or ""))
        return "\n".join(p for p in parts if p).strip()
    return ""


def completion_items(result):
    items = result.get("items") if isinstance(result, dict) else result
    out = []
    for item in items or []:
        if isinstance(item, dict) and (item.get("label")
                                       or item.get("insertText")):
            out.append({"label": str(item.get("label") or ""),
                        "insert": str(item.get("insertText")
                                      or item.get("label") or "")})
    return out


def apply_text_edits(text, edits):
    """把一组 LSP TextEdit 应用到文本上（按位置倒序，避免偏移错乱）。"""
    text = text or ""
    rows = [e for e in (edits or []) if isinstance(e, dict)]
    rows.sort(key=lambda e: (
        int(((e.get("range") or {}).get("start") or {}).get("line") or 0),
        int(((e.get("range") or {}).get("start") or {}).get("character") or 0)),
        reverse=True)
    for edit in rows:
        rng = edit.get("range") or {}
        start = position_to_offset(text, rng.get("start") or {})
        end = position_to_offset(text, rng.get("end") or {})
        if start > end:
            start, end = end, start
        text = text[:start] + str(edit.get("newText") or "") + text[end:]
    return text


def workspace_edit_changes(edit):
    """WorkspaceEdit → {绝对路径: [TextEdit]}；changes/documentChanges 都认。"""
    out = {}
    if not isinstance(edit, dict):
        return out
    changes = edit.get("changes")
    if isinstance(changes, dict):
        for uri, edits in changes.items():
            path = path_for_uri(uri)
            if path:
                out[path] = list(edits or [])
    for item in edit.get("documentChanges") or []:
        if not isinstance(item, dict):
            continue
        uri = (item.get("textDocument") or {}).get("uri")
        path = path_for_uri(uri)
        if path:
            out[path] = list(item.get("edits") or [])
    return out


def apply_workspace_edit(root, edit):
    """重命名的落盘：逐个文件读原文 → 应用编辑 → 原子写回（带快照）。"""
    changes = workspace_edit_changes(edit)
    if not changes:
        return {"ok": False, "changed": [], "errors": ["空的工作区编辑"],
                "reason": "语言服务没有返回可应用的改动"}
    changed, errors = [], []
    for path, edits in changes.items():
        try:
            with open(path, encoding="utf-8") as f:
                old = f.read()
        except OSError as e:
            errors.append("%s: %s" % (os.path.basename(path), str(e)[:120]))
            continue
        new = apply_text_edits(old, edits)
        if new == old:
            continue
        try:
            if root:
                from core.code_format import snapshot_file
                snapshot_file(root, path, old)
            tmp = path + ".lsp_tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new)
            os.replace(tmp, path)
            changed.append(path)
        except OSError as e:
            errors.append("%s: %s" % (os.path.basename(path), str(e)[:120]))
    return {"ok": bool(changed) and not errors, "changed": changed,
            "errors": errors,
            "reason": "" if changed else "没有文件被改动"}
