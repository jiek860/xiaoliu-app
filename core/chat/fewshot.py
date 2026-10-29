# -*- coding: utf-8 -*-
"""少样本示例选择（批次 42.5）。

从 ``core/chat/data/chat_fewshot.json``（随包种子；``data/chat_fewshot.json``
可覆盖）里按当前话题 / 计划动作挑 2 组短对话，让模型「照着长度和语气说话」，
而不是靠形容词描述风格。

只在人格卡 `on` 或规划器注入时使用；默认 shadow 不改变提示词。
"""
import json
import os

_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "chat_fewshot.json")
_BUILTIN = [
    {"u": "在吗", "a": "在，说。"},
    {"u": "今天累死了", "a": "听起来是被榨干了。先歇会儿，别急着复盘。"},
]
_CACHE = {}


def _read(path):
    try:
        stat = os.stat(path)
        hit = _CACHE.get(path)
        if hit and hit[0] == stat.st_mtime:
            return hit[1]
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        rows = [r for r in data if isinstance(r, dict) and r.get("u") and r.get("a")]
        _CACHE[path] = (stat.st_mtime, rows)
        return rows
    except (OSError, ValueError, TypeError):
        return []


def pick(base=".", topic="", act="", limit=2):
    """按 act（权重 2）与 topic（权重 1）打分，返回最多 limit 组。"""
    path = os.path.join(str(base or "."), "data", "chat_fewshot.json")
    rows = _read(path)
    if not rows and os.path.abspath(path) != _SEED_PATH:
        rows = _read(_SEED_PATH)       # 用户没放覆盖文件时用随包种子
    fallback = not rows
    rows = rows or list(_BUILTIN)
    topic = str(topic or "")
    act = str(act or "")
    scored = []
    for order, row in enumerate(rows):
        score = (2 if act and row.get("act") == act else 0) + (
            1 if topic and row.get("topic") == topic else 0)
        if score > 0:
            scored.append((-score, order, row))
    scored.sort(key=lambda item: (item[0], item[1]))
    if not scored and fallback:
        picked = rows[:max(0, int(limit or 0))]
        return [{"u": str(row["u"]), "a": str(row["a"])} for row in picked]
    return [{"u": str(row["u"]), "a": str(row["a"])}
            for _, _, row in scored[:max(0, int(limit or 0))]]
