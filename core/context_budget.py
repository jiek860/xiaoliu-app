# -*- coding: utf-8 -*-
"""上下文预算估算与裁剪。"""
import json


def estimate_tokens(obj):
    try:
        if isinstance(obj, str):
            text = obj
        else:
            text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = str(obj)
    return max(1, len(text) // 4)


def trim_messages(messages, max_tokens=6000, reserve=800):
    """保留 system、最后一条 user 和最近历史，尽量不截断关键指令。"""
    if not isinstance(messages, list):
        return messages
    budget = max(512, int(max_tokens) - int(reserve))
    if estimate_tokens(messages) <= budget:
        return messages
    systems = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
    users = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
    tail = messages[-6:]
    out = []
    used = 0
    for m in systems:
        used += estimate_tokens(m)
        out.append(m)
    # 最后一条用户消息必须保留
    last_user = users[-1] if users else None
    if last_user is not None and last_user not in out:
        used += estimate_tokens(last_user)
        out.append(last_user)
    for m in reversed(tail):
        if m in out:
            continue
        n = estimate_tokens(m)
        if used + n > budget:
            continue
        out.insert(len(out), m)
        used += n
    return out
