# -*- coding: utf-8 -*-
"""命令面板排序与别名（功能深化二期 · A4 命令面板）。

命令面板（``gui/command_palette.py``）原来只按「匹配度 + 固定分组」排序，
用户每次都要从头找。这里补两个很小的本地索引：

* **使用频次 / 最近使用**：执行一次记一次，``data/palette_usage.json``。
  排序 = 基础匹配 + 频次 + 最近使用加权，高频入口自然浮上来。
* **自定义别名**：用户可给入口起别名（``data/palette_aliases.json``），
  搜索别名也能命中。

不引入拼音依赖（拼音表太大，收益/体积不划算）；这里只做纯本地、
可测试的排序与别名，UI 侧按需调用。
"""
from __future__ import annotations

import json
import os
import time

from core.safe import atomic_write_json

_HALF_LIFE = 7 * 24 * 3600   # 最近使用的半衰期（7 天）


def _base(base):
    return str(base or os.getcwd())


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _usage_path(base):
    return os.path.join(_base(base), "data", "palette_usage.json")


def _aliases_path(base):
    return os.path.join(_base(base), "data", "palette_aliases.json")


# ---------------------------------------------------------------- 使用统计
def load_usage(base):
    data = _read_json(_usage_path(base), {})
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def record_use(base, entry_id, now=None):
    """记一次使用：count+1、last 更新。返回该 id 的最新统计。"""
    entry_id = str(entry_id or "").strip()
    if not entry_id:
        return {}
    data = load_usage(base)
    rec = data.get(entry_id) or {}
    rec["count"] = int(rec.get("count") or 0) + 1
    rec["last"] = float(now if now is not None else time.time())
    data[entry_id] = rec
    p = _usage_path(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        atomic_write_json(p, data)
    except (OSError, TypeError, ValueError):
        pass
    return rec


def frequency(base, entry_id):
    rec = load_usage(base).get(str(entry_id or "")) or {}
    return int(rec.get("count") or 0)


def recency(base, entry_id, now=None):
    """0~1，越接近现在越接近 1；没记录返回 0。"""
    rec = load_usage(base).get(str(entry_id or "")) or {}
    last = rec.get("last")
    if not last:
        return 0.0
    try:
        age = max(0.0, float(now if now is not None else time.time()) - float(last))
    except (TypeError, ValueError):
        return 0.0
    return 0.5 ** (age / _HALF_LIFE)


def score(base, entry_id, now=None):
    """排序加权值：频次 + 最近使用（0~1）。"""
    return frequency(base, entry_id) + recency(base, entry_id, now) * 2.0


# ---------------------------------------------------------------- 别名
def load_aliases(base):
    """返回 {entry_id: [别名, ...]}"""
    data = _read_json(_aliases_path(base), {})
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        names = [str(x).strip() for x in (v or []) if str(x).strip()]
        if names:
            out[str(k)] = names
    return out


def save_alias(base, entry_id, alias):
    """给某个入口加一个别名；已存在则忽略。返回最新别名表。"""
    entry_id = str(entry_id or "").strip()
    alias = str(alias or "").strip()
    if not (entry_id and alias):
        return load_aliases(base)
    data = load_aliases(base)
    names = data.setdefault(entry_id, [])
    if alias not in names:
        names.append(alias)
    p = _aliases_path(base)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        atomic_write_json(p, data)
    except (OSError, TypeError, ValueError):
        pass
    return data


def alias_hits(base, query):
    """别名里包含 query 的 entry_id 列表（不区分大小写）。"""
    q = str(query or "").strip().lower()
    if not q:
        return []
    out = []
    for entry_id, names in load_aliases(base).items():
        if any(q in n.lower() for n in names):
            out.append(entry_id)
    return out