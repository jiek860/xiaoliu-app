# -*- coding: utf-8 -*-
"""GUI Agent dual-channel, DPI and repair policy tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.gui_agent_quality import (  # noqa: E402
    DualChannelLocator, RetryPolicy, click_center, input_mode_for_text,
    monitor_at_point, normalize_rect_for_monitor, repair_strategy,
    to_logical_point, to_physical_point, verify_snapshot,
)


def test_monitor_geometry_and_dpi_roundtrip():
    monitors = [{"name": "left", "rect": [0, 0, 1920, 1080]},
                {"name": "right", "rect": [1920, 0, 2560, 1440]}]
    assert monitor_at_point(monitors, 2000, 200)["name"] == "right"
    logical = to_logical_point(300, 400, 1.5)
    physical = to_physical_point(logical["x"], logical["y"], 1.5)
    assert physical["x"] == 300 and physical["y"] == 400
    clamped = normalize_rect_for_monitor([1800, 100, 400, 200],
                                         [1920, 0, 2560, 1440], 1.25)
    assert clamped and clamped["x"] == 0


def test_dual_channel_locator_prefers_actionable_candidate():
    locator = DualChannelLocator()
    elements = [{"element_id": "e1", "name": "保存按钮", "type": "Button",
                 "rect": [10, 20, 80, 30], "actionable": True,
                 "confidence": 0.9, "source": "uia"}]
    hits = locator.locate("保存", elements=elements, top_k=3)
    assert hits
    assert hits[0]["element_id"] == "e1"
    assert click_center(hits[0]["rect"]) == {"x": 50, "y": 35}


def test_verification_of_text_and_element():
    before = {"ui_text": "home"}
    after = {"ui_text": "保存成功", "elements": [{"name": "完成"}]}
    assert verify_snapshot(before, after, {"text_contains": "保存成功"})["ok"]
    assert verify_snapshot(before, after, {"element_present": "完成"})["ok"]
    assert not verify_snapshot(before, after, {"window_title_contains": "设置"})["ok"]


def test_retry_and_repair_are_bounded():
    seq = RetryPolicy(max_retries=2).sequence()
    assert any(x.get("replan") for x in seq)
    assert repair_strategy({"name": "click"}, {"reason": "not found"}, 0)[0] == "refresh_snapshot"
    plan = repair_strategy({"name": "click"}, {"reason": "timeout"}, 2)
    assert "ask_user" in plan
    assert "replan" in plan


def test_input_mode_prefers_paste_for_chinese_and_multiline():
    assert input_mode_for_text("hello") == "type"
    assert input_mode_for_text("你好") == "paste"
    assert input_mode_for_text("line1\nline2") == "paste"
    assert input_mode_for_text("abc", ime_active=True) == "paste"
