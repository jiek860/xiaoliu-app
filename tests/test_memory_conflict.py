# -*- coding: utf-8 -*-
"""记忆 v2 冲突消解与过期（批次 43.3）。"""
import json
import os
import time

import pytest

from core.chat import memory_v2 as mv

DAY0 = time.mktime((2026, 10, 29, 12, 0, 0, 0, 0, -1))   # 周四


def _card(text, ctype, created, confidence=0.8):
    return mv.normalize({"text": text, "type": ctype,
                         "created_at": created, "confidence": confidence},
                        now=DAY0)


def test_due_at_relative_days():
    assert mv.due_at("提醒我明天交", DAY0) == DAY0 + 86400
    assert mv.due_at("3天后提醒我", DAY0) == DAY0 + 3 * 86400
    assert mv.due_at("后天再说", DAY0) == DAY0 + 2 * 86400


def test_due_at_weekday():
    assert mv.due_at("提醒我周五交周报", DAY0) == mv._morning(DAY0 + 86400)
    assert mv.due_at("下周一交", DAY0) == mv._morning(DAY0 + 4 * 86400)
    assert mv.due_at("周末去爬山", DAY0) == mv._morning(DAY0 + 2 * 86400)


def test_due_at_calendar_dates():
    nov5 = time.mktime((2026, 11, 5, 9, 0, 0, 0, 0, -1))
    assert mv.due_at("11月5日交", DAY0) == nov5
    assert mv.due_at("3号交", DAY0) == time.mktime(
        (2026, 11, 3, 9, 0, 0, 0, 0, -1))


def test_due_at_unknown_returns_zero():
    assert mv.due_at("有空再说", DAY0) == 0.0


def test_event_card_expires_in_seven_days():
    card = mv.make_card("周末去爬山", now=DAY0)
    assert card["expires_at"] == DAY0 + 7 * 86400


def test_commitment_expires_three_days_after_due():
    card = mv.make_card("提醒我明天交周报", now=DAY0)
    assert card["due_at"] == DAY0 + 86400
    assert card["expires_at"] == DAY0 + 4 * 86400


def test_explicit_expiry_is_preserved():
    card = mv.normalize({"text": "这周在出差", "type": "event",
                         "created_at": DAY0, "expires_at": DAY0 - 1}, now=DAY0)
    assert card["expires_at"] == DAY0 - 1


def test_near_duplicate_preference_newest_wins():
    old = _card("我喜欢用短句", "preference", DAY0 - 86400)
    new = _card("我喜欢用短句聊天", "preference", DAY0)
    kept = mv.resolve_conflicts([old, new])
    assert len(kept) == 1
    assert kept[0]["text"] == "我喜欢用短句聊天"
    assert kept[0]["conflicts_with"] == [old["id"]]
    assert kept[0]["confidence"] == pytest.approx(0.7)


def test_opposite_preference_newest_wins():
    old = _card("我喜欢短句", "preference", DAY0 - 86400)
    new = _card("我讨厌短句", "preference", DAY0)
    kept = mv.resolve_conflicts([old, new])
    assert len(kept) == 1
    assert kept[0]["text"] == "我讨厌短句"


def test_unrelated_preferences_both_kept():
    a = _card("我喜欢短句", "preference", DAY0 - 86400)
    b = _card("我喜欢蓝色", "preference", DAY0)
    assert len(mv.resolve_conflicts([a, b])) == 2


def test_near_duplicate_fact_newest_wins_and_drops_confidence():
    a = _card("我住在杭州", "fact", DAY0 - 86400)
    b = _card("我住在杭州西湖区", "fact", DAY0)
    kept = mv.resolve_conflicts([a, b])
    assert len(kept) == 1
    assert kept[0]["text"] == "我住在杭州西湖区"
    assert kept[0]["confidence"] == pytest.approx(0.7)


def test_recall_skips_superseded_preference(tmp_path):
    path = os.path.join(str(tmp_path), "data", "memory_cards.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        for card in (_card("我喜欢用短句", "preference", DAY0 - 86400),
                     _card("我喜欢用短句聊天", "preference", DAY0)):
            fp.write(json.dumps(card, ensure_ascii=False) + "\n")
    cards = mv.MemoryV2(str(tmp_path)).recall("我喜欢什么", now=DAY0)
    assert len(cards) == 1
    assert cards[0]["text"] == "我喜欢用短句聊天"


def test_recall_skips_expired_event(tmp_path):
    card = mv.make_card("周末去爬山", now=DAY0 - 30 * 86400)
    card["expires_at"] = DAY0 - 1
    path = os.path.join(str(tmp_path), "data", "memory_cards.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps(card, ensure_ascii=False) + "\n")
    assert mv.MemoryV2(str(tmp_path)).recall("周末爬山", now=DAY0) == []


def test_conflicts_with_survives_roundtrip(tmp_path):
    old = _card("我喜欢用短句", "preference", DAY0 - 86400)
    new = _card("我喜欢用短句聊天", "preference", DAY0)
    new["conflicts_with"] = [old["id"]]
    path = os.path.join(str(tmp_path), "data", "memory_cards.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(json.dumps(new, ensure_ascii=False) + "\n")
    loaded = mv.load_cards(path, now=DAY0)[0]
    assert loaded["conflicts_with"] == [old["id"]]


def test_resolve_is_stable_for_same_input():
    a = _card("我喜欢用短句", "preference", DAY0 - 86400)
    b = _card("我喜欢用短句聊天", "preference", DAY0)
    first = mv.resolve_conflicts([a, b])
    second = mv.resolve_conflicts([b, a])
    assert [c["id"] for c in first] == [c["id"] for c in second]
