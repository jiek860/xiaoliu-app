# -*- coding: utf-8 -*-
"""「记得的你」逻辑层（批次 43.4）：查看/纠正/删除/导出/搜索。"""
import json
import os

from core.chat.memory_v2 import MemoryV2
from gui.memory_view_dialog import (
    delete_card, display_text, edit_card, export_cards, load_cards,
    save_cards, search_cards, visible_cards,
)


def _path(base):
    return os.path.join(str(base), "data", "memory_cards.jsonl")


def _write(base, rows):
    os.makedirs(os.path.dirname(_path(base)), exist_ok=True)
    with open(_path(base), "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write((row if isinstance(row, str)
                      else json.dumps(row, ensure_ascii=False)) + "\n")


def test_load_cards_missing_file(tmp_path):
    assert load_cards(_path(tmp_path)) == []


def test_load_cards_skips_bad_lines(tmp_path):
    _write(tmp_path, [{"facts": ["喜欢短句"]}, "{bad", {"text": "新卡"}])
    assert len(load_cards(_path(tmp_path))) == 2


def test_display_text_prefers_v2_then_facts():
    assert display_text({"text": "喜欢短句", "facts": ["旧内容"]}) == "喜欢短句"
    assert display_text({"facts": ["喜欢短句", "住在杭州"]}) == "喜欢短句、住在杭州"
    assert display_text({}) == ""


def test_visible_cards_keeps_original_index_past_100(tmp_path):
    cards = [{"text": "第%d条" % i} for i in range(150)]
    shown = visible_cards(cards)
    assert len(shown) == 100
    assert shown[0][0] == 50
    assert shown[-1][0] == 149
    assert shown[-1][1]["text"] == "第149条"


def test_visible_cards_short_list():
    cards = [{"text": "a"}, {"text": "b"}]
    assert visible_cards(cards) == [(0, cards[0]), (1, cards[1])]


def test_edit_card_updates_text_facts_and_id():
    card = {"facts": ["喜欢长句"], "type": "preference",
            "created_at": 1_790_000_000.0}
    edited = edit_card(card, "喜欢短句", now=1_790_000_100.0)
    assert edited["text"] == "喜欢短句"
    assert edited["facts"] == ["喜欢短句"]
    assert edited["id"].startswith("m_")
    assert edited["updated_at"] == 1_790_000_100.0
    assert edited["type"] == "preference"
    assert card.get("text") is None          # 不改原对象


def test_edit_card_empty_returns_original():
    card = {"text": "喜欢短句"}
    assert edit_card(card, "  ") is card


def test_delete_card_removes_exact_index():
    cards = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    out = delete_card(cards, 1)
    assert [c["text"] for c in out] == ["a", "c"]
    assert len(cards) == 3                    # 不改原列表


def test_delete_card_out_of_range_is_noop():
    cards = [{"text": "a"}]
    assert delete_card(cards, 9) == cards
    assert delete_card(cards, "x") == cards


def test_save_cards_roundtrip_and_atomic(tmp_path):
    path = _path(tmp_path)
    assert save_cards(path, [{"text": "喜欢短句"}]) is True
    assert load_cards(path)[0]["text"] == "喜欢短句"
    assert not os.path.exists(path + ".tmp")


def test_save_cards_failure_returns_false(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.mkdir()
    assert save_cards(str(blocker), [{"text": "x"}]) is False


def test_search_cards_finds_v2_and_legacy():
    cards = [{"text": "喜欢短句"}, {"facts": ["住在杭州"]}, {"text": "别的"}]
    assert [c["text"] for c in search_cards(cards, "短句")] == ["喜欢短句"]
    assert [c["facts"] for c in search_cards(cards, "杭州")] == [["住在杭州"]]
    assert search_cards(cards, "") == []


def test_export_cards_writes_json(tmp_path):
    target = tmp_path / "out.json"
    count = export_cards(str(target), [{"text": "a"}, {"text": "b"}])
    assert count == 2
    with open(target, encoding="utf-8") as fp:
        assert len(json.load(fp)) == 2


def test_export_cards_failure_returns_minus_one(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.mkdir()
    assert export_cards(str(blocker), [{"text": "a"}]) == -1


def test_deleted_card_is_no_longer_recalled(tmp_path):
    old = {"text": "我喜欢用短句", "type": "preference",
           "created_at": 1_790_000_000.0}
    keep = {"text": "我喜欢蓝色", "type": "preference",
            "created_at": 1_790_000_100.0}
    _write(tmp_path, [old, keep])
    cards = delete_card(load_cards(_path(tmp_path)), 0)
    assert save_cards(_path(tmp_path), cards) is True
    found = MemoryV2(str(tmp_path)).recall("我喜欢什么", now=1_790_000_200.0)
    assert [c["text"] for c in found] == ["我喜欢蓝色"]


def test_edited_card_text_is_recalled(tmp_path):
    _write(tmp_path, [{"text": "我喜欢长句", "type": "preference",
                       "created_at": 1_790_000_000.0}])
    cards = load_cards(_path(tmp_path))
    cards[0] = edit_card(cards[0], "我喜欢短句", now=1_790_000_100.0)
    assert save_cards(_path(tmp_path), cards) is True
    found = MemoryV2(str(tmp_path)).recall("我喜欢什么", now=1_790_000_200.0)
    assert found[0]["text"] == "我喜欢短句"


def test_deleted_card_keeps_other_lines_intact(tmp_path):
    _write(tmp_path, [{"text": "a"}, {"text": "b"}, {"text": "c"}])
    cards = delete_card(load_cards(_path(tmp_path)), 1)
    save_cards(_path(tmp_path), cards)
    assert [c["text"] for c in load_cards(_path(tmp_path))] == ["a", "c"]
