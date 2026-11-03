# -*- coding: utf-8 -*-
"""聊天步骤条（第 5 批 A4）：无头 Qt 下能构造、能渲染、能单步取消。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from core.pipeline import stage_bus as bus  # noqa: E402
from gui.chat_stage_strip import ChatStageStrip  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}

    def rule(self, key, default=None):
        return self.rules.get(key, default)


@pytest.fixture(autouse=True)
def _clean_bus():
    bus.reset()
    yield
    bus.reset()


def _strip(rules=None):
    return ChatStageStrip(None, trunk=FakeTrunk(rules))


def test_strip_starts_hidden_and_empty():
    strip = _strip()
    assert strip.isHidden() is True
    assert strip.summary.text() == ""


def test_strip_shows_running_stage():
    strip = _strip()
    strip.apply("stage", {"stage": "接收消息", "status": "running",
                          "step": "s1", "percent": 0.0, "total": 6})
    assert strip.isHidden() is False
    assert "接收消息" in strip.summary.text()
    assert "0%" in strip.summary.text()


def test_strip_merges_same_stage_name():
    strip = _strip()
    strip.apply("stage", {"stage": "模型生成", "status": "running", "step": "s1"})
    strip.apply("stage", {"stage": "模型生成", "status": "ok", "ms": 1500})
    # 同名步骤只占一行，不能越跑越长
    assert len(strip._steps) == 1
    assert strip._steps[0]["status"] == "ok"


def test_strip_shows_eta_and_tool_count():
    strip = _strip()
    strip.apply("stage", {"stage": "模型生成", "status": "running",
                          "percent": 0.5, "eta": 6.0})
    strip.apply("tool_call", {"tool": "code_runner", "args": {"代码行数": 3}})
    strip.apply("tool_result", {"tool": "code_runner", "ok": True,
                                "result": "运行成功", "ms": 800})
    text = strip.summary.text()
    assert "50%" in text and "预计还需 6 秒" in text
    assert "工具 1 次（成功 1）" in text


def test_strip_rule_off_stays_hidden_but_records():
    strip = _strip({"聊天.过程可见": "off"})
    strip.apply("stage", {"stage": "接收消息", "status": "ok"})
    assert strip.isHidden() is True
    assert strip.rows()[0]["stage"] == "接收消息"


def test_strip_reset_clears_rows():
    strip = _strip()
    strip.apply("stage", {"stage": "接收消息", "status": "ok"})
    strip.reset()
    assert strip.rows() == []
    assert strip.summary.text() == ""
    assert strip.isHidden() is True


def test_strip_finish_hides():
    strip = _strip()
    strip.apply("stage", {"stage": "接收消息", "status": "ok"})
    strip.finish()
    assert strip.isHidden() is True


def test_strip_cancel_link_cancels_step():
    """取消这一步：总线状态真变了、取消链接消失、提示语真的显示出来。

    S4 起这里不再断言 `cancelRequested` 信号 —— 那个信号全项目没有消费者，
    已删除（功能本来就由 `stage_bus.cancel_step()` 自己完成，见模块 docstring）。
    """
    strip = _strip()
    step = bus.begin_step("模型生成")
    strip.apply("stage", {"stage": "模型生成", "status": "running",
                          "step": step.sid})
    assert "cancel://" in strip.links.text()
    strip._on_link("cancel://%s" % step.sid)
    assert step.cancelled is True
    assert strip._running_step == ""
    assert "cancel://" not in strip.links.text()
    # 提示语要真出现在摘要里（S4 之前它写在 _render() 前面，被整段覆盖，从没显示过）
    assert "（已取消这一步）" in strip.summary.text()


def test_strip_has_no_unconnected_signals():
    """S4：两个没有消费者的信号已删除，不能再长回来（tools/check_signals.py 同款口径）"""
    assert not hasattr(ChatStageStrip, "cancelRequested")
    assert not hasattr(ChatStageStrip, "detailRequested")


def test_strip_keeps_only_recent_steps():
    strip = _strip()
    strip.apply("stage", {"stage": "一", "status": "ok"})
    strip.apply("stage", {"stage": "二", "status": "ok"})
    strip.apply("stage", {"stage": "三", "status": "ok"})
    lines = strip.summary.text().count("✓")
    assert lines == 3
