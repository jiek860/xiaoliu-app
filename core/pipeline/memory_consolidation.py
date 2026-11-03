# -*- coding: utf-8 -*-
"""会话结束的记忆巩固（第 4 批 A2 / 深度②③）。

为什么要它
----------
写入侧原本只有两条路径：强信号立即写、每 5 轮写一张摘要卡（批次 43.2）。
真实用起来有两个漏洞：

* 一次会话聊了十几轮、结束时只留下几张"近几轮聊到…"的摘要卡，
  真正值得长期记住的那几句（"我住在杭州"）如果没命中强信号词就丢了；
* 新事实覆盖旧事实时没有任何痕迹 —— 用户只看到"记错了"，查不出是谁覆盖了谁。

这里做"会话结束提炼"：把这段会话的用户原话扫一遍，抽强信号卡 + 一张会话摘要卡，
按 bigram Jaccard 去重后写入 ``data/memory_cards.jsonl``；写入前用
``memory_v2.resolve_conflicts`` 做冲突消解（新卡覆盖旧卡、赢家记 ``conflicts_with``），
并把每次覆盖写进 ``data/memory_conflicts.jsonl`` 留痕。

约束：纯规则、零模型调用；任何异常返回 ``{"written": 0}``，绝不影响聊天。
"""
from __future__ import annotations

import json
import os
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_MAX_MESSAGES = 40      # 只看最近这么多条用户原话
SUMMARY_MIN_ROUNDS = 3         # 至少聊了这么多轮才写会话摘要卡
DUPLICATE_JACCARD = 0.55       # 与已有卡片认为"同一件事"的阈值
CONFLICT_JACCARD = 0.55        # 冲突消解阈值（与 memory_v2 默认一致）
_CONFLICT_FILE = "memory_conflicts.jsonl"


def _user_texts(messages):
    """把各种消息写法都收成"用户原话"列表（保序）。

    兼容 ``{"role": "user", "content": ...}`` / ``{"u": ..., "a": ...}`` /
    ``{"text": ...}`` / 纯字符串（纯字符串按用户原话处理）。
    """
    out = []
    for msg in messages or []:
        if isinstance(msg, str):
            text = msg
        elif isinstance(msg, dict):
            role = str(msg.get("role") or msg.get("r") or ""
                       ).strip().lower()
            if role and role not in ("u", "user", "human"):
                continue
            text = msg.get("content") or msg.get("text") or msg.get("u") or ""
        else:
            continue
        text = " ".join(str(text or "").split())
        if text:
            out.append(text)
    return out


def _too_similar(text, pool, threshold=DUPLICATE_JACCARD):
    from core.chat import memory_v2 as mv
    return any(mv.jaccard(text, other) >= float(threshold) for other in pool)


def _log_conflicts(base, conflicts, now):
    """把"谁覆盖了谁"落盘留痕（深度③）；失败静默。"""
    if not conflicts:
        return 0
    path = os.path.join(str(base or "."), "data", _CONFLICT_FILE)
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fp:
            for row in conflicts:
                fp.write(json.dumps(dict(row, at=float(now)),
                                    ensure_ascii=False) + "\n")
        return len(conflicts)
    except Exception as e:
        _x6_swallowed(__name__, e, "log_conflicts")
        return 0


def load_conflicts(base=".", limit=20):
    """读最近的冲突留痕（给记忆窗口/报告展示）。"""
    path = os.path.join(str(base or "."), "data", _CONFLICT_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fp:
            lines = fp.readlines()[-max(1, int(limit or 20)):]
    except (OSError, ValueError):
        return []
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except (ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "bad_conflict_line")
    return rows


def consolidate_session(messages, *, base=".", now=None,
                        max_messages=DEFAULT_MAX_MESSAGES, dry_run=False):
    """会话结束提炼：抽强信号卡 + 会话摘要卡 → 去重 → 冲突消解 → 写入。

    返回 ``{written, cards, skipped, conflicts, dry_run}``；
    ``dry_run=True`` 只算不写（用于观测"本来会记住什么"）。
    """
    from core.chat import memory_v2 as mv

    now = float(now or time.time())
    texts = _user_texts(messages)[-max(1, int(max_messages or 1)):]
    if not texts:
        return {"written": 0, "cards": [], "skipped": [], "conflicts": [],
                "dry_run": bool(dry_run)}
    path = os.path.join(str(base or "."), "data", "memory_cards.jsonl")
    existing = mv.load_cards(path, now=now)
    known = [str(card.get("text") or "") for card in existing]
    known_ids = {str(card.get("id") or "") for card in existing}

    cards, skipped = [], []

    def _take(card):
        if not card or not card.get("id"):
            return
        if card["id"] in known_ids:
            skipped.append(card.get("text", ""))
            return
        if _too_similar(card.get("text", ""), known):
            skipped.append(card.get("text", ""))
            return
        known_ids.add(card["id"])
        known.append(card.get("text", ""))
        cards.append(card)

    for text in texts:
        for card in mv.extract_cards(text, now=now, strong_only=True):
            _take(card)
    if len(texts) >= SUMMARY_MIN_ROUNDS:
        for card in mv.summarize_cards(texts[-5:], now=now):
            _take(card)

    conflicts = []
    if cards:
        resolved = mv.resolve_conflicts(list(existing) + list(cards),
                                        threshold=CONFLICT_JACCARD)
        kept_ids = {str(card.get("id") or "") for card in resolved}
        cards = [card for card in cards if str(card.get("id") or "") in kept_ids]
        for card in resolved:
            losers = list(card.get("conflicts_with") or [])
            if losers:
                conflicts.append({"winner": card.get("id"),
                                  "text": str(card.get("text") or "")[:60],
                                  "losers": losers,
                                  "reason": "同类事实：新卡按时间/置信度覆盖旧卡"})
    written = 0 if dry_run else mv.append_cards(path, cards, now=now)
    if not dry_run:
        _log_conflicts(base, conflicts, now)
    return {"written": written, "cards": cards, "skipped": skipped,
            "conflicts": conflicts, "dry_run": bool(dry_run)}
