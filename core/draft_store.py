# -*- coding: utf-8 -*-
"""发送草稿与输入历史（功能深化二期 · A1 发送）。

三个小能力，都只做本地文件读写，不依赖 Qt：

* 草稿：输入框内容（防抖后）存到 ``data/drafts/<会话>.json``，
  切回会话/重启时可以恢复「上次没发出去的话」。
* 输入历史：最近 N 条已发送文本存 ``data/input_history.json``，
  输入框用 ↑/↓ 回滚上一句（解码层可选接入）。
* 清理：发送成功后清掉该会话草稿，避免下次误恢复旧内容。

设计约束
--------
* 走 ``core.safe.atomic_write_json`` 原子写，中途崩不会写出半个文件。
* 读失败一律返回默认值（草稿是体验优化，不能因为坏文件拦住发送）。
* 文件名做白名单清洗，避免会话 id 里带 ``../`` 越界。
"""
from __future__ import annotations

import json
import os
import time

from core.safe import atomic_write_json

HISTORY_LIMIT = 50


def _base(base):
    return str(base or os.getcwd())


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _safe_name(session_id):
    """会话 id -> 文件名：只留字母/数字/-/_，其余转下划线。"""
    s = str(session_id or "default").strip() or "default"
    out = "".join(c if (c.isalnum() or c in "-_") else "_" for c in s)
    return out[:80] or "default"


def _draft_path(base, session_id):
    return os.path.join(_base(base), "data", "drafts",
                        _safe_name(session_id) + ".json")


def _history_path(base):
    return os.path.join(_base(base), "data", "input_history.json")


# ---------------------------------------------------------------- 草稿
def save_draft(base, session_id, text):
    """保存草稿；空文本等于清理。返回是否成功。"""
    text = str(text or "")
    if not text.strip():
        return clear_draft(base, session_id)
    p = _draft_path(base, session_id)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        atomic_write_json(p, {"text": text, "ts": time.time()})
        return True
    except (OSError, TypeError, ValueError):
        return False


def load_draft(base, session_id):
    """读草稿文本；没有/坏了返回空串。"""
    data = _read_json(_draft_path(base, session_id), {})
    if not isinstance(data, dict):
        return ""
    return str(data.get("text") or "") if data.get("text") else ""


def has_draft(base, session_id):
    return bool(load_draft(base, session_id))


def clear_draft(base, session_id):
    """删掉该会话草稿；不存在也算成功。"""
    try:
        os.remove(_draft_path(base, session_id))
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- 历史
def get_history(base):
    """返回最近发送文本列表（旧的在前，新的在后）。"""
    data = _read_json(_history_path(base), {})
    items = data.get("items") if isinstance(data, dict) else None
    return [str(x) for x in items] if isinstance(items, list) else []


def push_history(base, text, limit=HISTORY_LIMIT):
    """把一条已发送文本加入历史；与上一条重复则不重复记。"""
    text = str(text or "").strip()
    if not text:
        return get_history(base)
    items = get_history(base)
    if items and items[-1] == text:
        return items
    items.append(text)
    if len(items) > max(1, int(limit)):
        items = items[-max(1, int(limit)):]
    p = _history_path(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        atomic_write_json(p, {"items": items})
    except (OSError, TypeError, ValueError):
        return items
    return items


def clear_history(base):
    try:
        os.remove(_history_path(base))
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False