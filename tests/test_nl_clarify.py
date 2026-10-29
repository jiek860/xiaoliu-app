# -*- coding: utf-8 -*-
"""澄清与计划卡（批次 44.3）：只问一个关键问题 + 复用 code_plan。"""
from core.nl.clarify import (ask, fill_from_context, merge_answer,
                             missing_slot, plan_card)
from core.nl.intent import route


def test_missing_target_asks_one_question():
    info = route("帮我改一下这个")
    reply = ask(info)
    assert reply["kind"] == "clarify"
    assert reply["slot"] == "target"
    assert reply["options"] == []
    assert "哪个文件或符号" in reply["question"]


def test_context_current_file_fills_slot_without_asking():
    info = route("修复这个")
    assert missing_slot(info) == "target"
    reply = ask(info, context={"current_file": "core/x.py"})
    assert reply["kind"] == "ready"
    targets = reply["info"]["targets"]
    assert any(t["type"] == "file" and t["value"] == "core/x.py"
               for t in targets)
    assert reply["info"]["context_filled"] == "current_file"


def test_search_can_use_selection_as_query():
    info = route("搜索")
    filled = fill_from_context(info, {"selection": "def route_goal"})
    assert filled["query"].startswith("def route_goal")
    assert missing_slot(filled) == ""


def test_unresolved_candidates_become_options():
    info = route("重构 find_all")
    resolved = [{"type": "symbol", "ok": False,
                 "candidates": ["find_all", "find_all_items", "find_all_by"]}]
    reply = ask(info, resolved=resolved)
    assert reply["kind"] == "clarify"
    assert len(reply["options"]) <= 5
    assert "哪个" in reply["question"]


def test_ready_when_all_slots_present():
    info = route("修复 core/agent_router.py 的报错")
    reply = ask(info)
    assert reply["kind"] == "ready" and reply["question"] == ""


def test_run_test_without_name_asks_which_test():
    reply = ask(route("帮我测试一下"))
    assert reply["kind"] == "clarify" and reply["slot"] == "test"
    assert "哪个测试" in reply["question"]


def test_search_without_query_asks_what():
    reply = ask(route("搜索"))
    assert reply["kind"] == "clarify" and reply["slot"] == "query"
    assert "想搜什么" in reply["question"]


def test_merge_answer_sets_search_query():
    info = merge_answer(route("搜索"), "route_goal 在哪")
    assert info["query"] == "route_goal 在哪"
    assert missing_slot(info) == ""


def test_merge_answer_sets_test_target():
    info = merge_answer(route("帮我测试一下"), "tests/test_x.py")
    assert missing_slot(info) == ""
    assert any(t["type"] == "test" for t in info["targets"])


def test_merge_answer_all_tests():
    info = merge_answer(route("跑一下测试"), "全部")
    assert info["run_all_tests"] is True
    assert missing_slot(info) == ""


def test_merge_answer_symbol_when_no_path():
    info = merge_answer(route("帮我改一下这个"), "route_goal")
    assert info["targets"][-1] == {"type": "symbol", "value": "route_goal"}
    assert missing_slot(info) == ""


def test_plan_card_has_checkable_steps():
    card = plan_card("把路由层拆成三个模块，补测试并跑全量回归")
    assert card["needs_plan"] is True
    assert card["editable"] is True
    assert len(card["steps"]) >= 3
    for index, step in enumerate(card["steps"]):
        assert step["done"] is False
        assert step["index"] == index
        assert step["title"]
    assert card["confirm_text"].startswith("确认后")


def test_plan_card_simple_goal_does_not_need_plan():
    card = plan_card("打开 core/x.py")
    assert card["needs_plan"] is False
    assert card["steps"]


def test_plan_card_normalizes_model_plan():
    data = {"summary": "自定义计划",
            "steps": [{"title": "改 A", "purpose": "因为 B",
                       "files": ["core/x.py"], "risk": "low"},
                      {"title": "跑测试"}],
            "risks": ["可能冲突"], "tests": ["tests/test_x.py"]}
    card = plan_card("改 A", data=data)
    assert card["summary"] == "自定义计划"
    assert [s["title"] for s in card["steps"]] == ["改 A", "跑测试"]
    assert card["steps"][0]["files"] == ["core/x.py"]
    assert card["risks"] == ["可能冲突"]
    assert card["tests"] == ["tests/test_x.py"]
    assert card["fallback"] is False


def test_plan_card_uses_intent_targets_as_files():
    info = route("修复 core/agent_router.py 的报错")
    card = plan_card("修复 core/agent_router.py 的报错", info=info)
    assert "core/agent_router.py" in card["steps"][0]["files"]
