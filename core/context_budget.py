# -*- coding: utf-8 -*-
"""上下文预算估算与裁剪（第 2 批：分渠道配额）。

原来只有一个总预算 ``max_tokens``：谁先被塞进去谁占坑，某一类消息
（比如超长的检索片段）就可以把历史对话挤空。这里把预算拆成
「系统 / 人格 / 历史 / 检索 / 工具」五路，各自有配额：

* **系统与人格永不裁**（裁掉就等于改人设/丢指令）；
* 历史、检索、工具按配额从**最新往前**保留，过期消息整条丢弃；
* 最后一条 user 消息永远保留（模型没有当前问题就答不了）。

接口保持向后兼容：``trim_messages(messages, max_tokens, reserve)`` 仍然是
唯一入口，内部分渠道执行；需要更细控制时用 ``trim_by_channel``。
"""
from __future__ import annotations

import json

# 五路预算的默认占比（合计 1.0）
DEFAULT_SHARES = {
    "system": 0.20,
    "persona": 0.10,
    "history": 0.45,
    "rag": 0.20,
    "tools": 0.05,
}

CHANNELS = ("system", "persona", "history", "rag", "tools")

# 这些渠道"必须有"，配额只用于提示词组装参考，不参与丢弃
KEEP_CHANNELS = ("system", "persona")

_RAG_HINTS = ("相关知识", "参考资料", "检索结果", "【知识】", "RAG")
_TOOL_HINTS = ("可用工具", "工具调用", "你可以调用", "tool_call")
_PERSONA_HINTS = ("你是小6", "人格", "说话风格")

SUMMARY_PREFIX = "【早前对话摘要】"
SUMMARY_MAX_TOKENS = 400
_SUMMARY_MAX_ITEMS = 8
_SUMMARY_ITEM_CHARS = 60
_SENTENCE_END = "。！？!?\n"


def estimate_tokens(obj):
    try:
        if isinstance(obj, str):
            text = obj
        else:
            text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = str(obj)
    return max(1, len(text) // 4)


def channel_of(message):
    """把一条消息归到某个渠道（无法判断时按历史对话）。"""
    if not isinstance(message, dict):
        return "history"
    role = str(message.get("role") or "").lower()
    content = str(message.get("content") or "")
    if role == "system":
        if any(h in content for h in _PERSONA_HINTS):
            return "persona"
        if any(h in content for h in _TOOL_HINTS):
            return "tools"
        if any(h in content for h in _RAG_HINTS):
            return "rag"
        return "system"
    if role == "tool":
        return "tools"
    if any(h in content for h in _RAG_HINTS):
        return "rag"
    return "history"


def channel_budgets(total_tokens, shares=None):
    """把总预算按占比拆成五路（取整，至少 1 token）。"""
    total = max(1, int(total_tokens))
    merged = dict(DEFAULT_SHARES)
    if isinstance(shares, dict):
        for key, value in shares.items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if key in merged and value > 0:
                merged[key] = value
    weight = sum(merged.values()) or 1.0
    return {key: max(1, int(total * value / weight))
            for key, value in merged.items()}


def _first_sentence(text):
    out = []
    for ch in str(text or "").strip():
        if ch in _SENTENCE_END:
            break
        out.append(ch)
    got = "".join(out).strip()
    if not got:
        got = str(text or "").strip()
    return got[:_SUMMARY_ITEM_CHARS]


def roll_up(messages, max_tokens=SUMMARY_MAX_TOKENS,
            max_items=_SUMMARY_MAX_ITEMS):
    """把一批消息压成一条确定性摘要（第 3 批深度②：滚动摘要）。

    为什么不调模型做摘要：压缩本身不能引入新的等待与不确定性 —— 一旦模型
    不可用就再也压不出来了。这里只做**确定性抽取**：每条取首句并截断，
    按原顺序拼成"用户：… / 助手：…"，条数与 token 都有上限。

    返回一条 ``{"role": "system", "content": "【早前对话摘要】…"}``；
    没有可用内容时返回 None。
    """
    if not isinstance(messages, list):
        return None
    lines, budget = [], max(1, int(max_tokens))
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role = str(msg.get("role") or "").lower()
        if role == "user":
            line = "用户：" + _first_sentence(content)
        elif role == "assistant":
            line = "助手：" + _first_sentence(content)
        else:
            line = _first_sentence(content)
        candidate = "\n".join(lines + [line])
        if estimate_tokens(SUMMARY_PREFIX + candidate) > budget and lines:
            break
        lines.append(line)
        if len(lines) >= max_items:
            break
    if not lines:
        return None
    return {"role": "system", "content": SUMMARY_PREFIX + "\n" + "\n".join(lines)}


def _insert_summary(out, summary):
    """把摘要插到开头的系统/人格消息之后（别打断 system 的连续性）。"""
    idx = 0
    for i, msg in enumerate(out):
        if isinstance(msg, dict) and str(msg.get("role")) == "system":
            idx = i + 1
        else:
            break
    return out[:idx] + [summary] + out[idx:]


def trim_by_channel(messages, max_tokens=6000, reserve=800, shares=None,
                    summarize=True):
    """分渠道裁剪：系统/人格必留，其余按配额从最新往前保留。"""
    if not isinstance(messages, list):
        return messages
    budget = max(512, int(max_tokens) - int(reserve))
    if estimate_tokens(messages) <= budget:
        return messages
    quotas = channel_budgets(budget, shares)
    used = {key: 0 for key in CHANNELS}
    keep = [False] * len(messages)
    last_user = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, dict) and str(msg.get("role")) == "user":
            last_user = i
        if channel_of(msg) in KEEP_CHANNELS:
            keep[i] = True
            used[channel_of(msg)] += estimate_tokens(msg)
    # 从最新往前保留，保证"最近说的话"优先于早期内容
    for i in range(len(messages) - 1, -1, -1):
        if keep[i]:
            continue
        msg = messages[i]
        ch = channel_of(msg)
        need = estimate_tokens(msg)
        if ch not in quotas:
            continue
        if i == last_user:
            keep[i] = True
            used[ch] += need
            continue
        if used[ch] + need > quotas[ch]:
            continue
        keep[i] = True
        used[ch] += need
    out = [msg for i, msg in enumerate(messages) if keep[i]]
    # 深度②：被裁掉的早期对话不直接丢，压成一条摘要塞回去（有剩余预算才做）
    if summarize:
        dropped = [msg for i, msg in enumerate(messages)
                   if not keep[i] and channel_of(msg) not in KEEP_CHANNELS]
        headroom = budget - estimate_tokens(out)
        if len(dropped) >= 2 and headroom > 20:
            summary = roll_up(dropped, max_tokens=min(SUMMARY_MAX_TOKENS, headroom))
            if summary:
                out = _insert_summary(out, summary)
    return out or messages[-1:]


def fit_text(text, max_tokens, tail="\n…（已按预算截断）"):
    """把一段文本裁到 token 预算内（第 8 批：相关代码片段专用的确定性裁剪）。

    按行裁而不是按字符裁：代码/片段截在行中间会变成语法垃圾。
    第一行超预算时才会退化成按字符截。
    """
    body = str(text or "")
    budget = max(16, int(max_tokens))
    if estimate_tokens(body) <= budget:
        return body
    lines, used = [], 0
    for line in body.splitlines():
        need = estimate_tokens(line + "\n")
        if used + need > max(1, budget - estimate_tokens(tail)):
            break
        lines.append(line)
        used += need
    if not lines:
        keep = max(1, (budget - estimate_tokens(tail)) * 4)
        return body[:keep] + tail
    return "\n".join(lines) + tail


def trim_messages(messages, max_tokens=6000, reserve=800, shares=None):
    """保留 system、最后一条 user 和最近历史，尽量不截断关键指令。"""
    return trim_by_channel(messages, max_tokens=max_tokens, reserve=reserve,
                           shares=shares)
