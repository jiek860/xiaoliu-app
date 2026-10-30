# -*- coding: utf-8 -*-
"""话题时间线：条目过滤、跳转定位与对话框。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QTextEdit, QWidget  # noqa: E402

from gui import chat_timeline as tl  # noqa: E402

_app = QApplication.instance() or QApplication([])

MSGS = [{"role": "u", "text": "贪吃蛇游戏"},
        {"role": "a", "text": "写好了"},
        {"role": "u", "text": "报表也做一下"}]


class _Win(QWidget):
    def __init__(self):
        super().__init__()
        self.chat = QTextEdit()
        self.chat.setPlainText("贪吃蛇游戏\n写好了\n报表也做一下")


def test_timeline_items_and_filter():
    items = tl.timeline_items(MSGS)
    assert items and items[0]["topic"]
    assert tl.timeline_items(MSGS, "报表")[0]["topic"].find("报表") >= 0
    assert tl.timeline_items(MSGS, "不存在") == []


def test_scroll_to_text_finds_and_misses():
    w = _Win()
    assert tl.scroll_to_text(w.chat, "报表也做一下") is True
    assert tl.scroll_to_text(w.chat, "没有这句") is False
    assert tl.scroll_to_text(w.chat, "") is False


def test_dialog_lists_and_filters():
    w = _Win()
    d = tl.TimelineDialog(w)
    assert d.list.count() >= 1
    d.filter.setText("报表")
    assert d.list.count() == 1
    d.filter.setText("不存在")
    assert d.list.count() == 1          # 占位行「没有匹配的话题」
    assert "没有匹配" in d.list.item(0).text()


def test_dialog_jump_selects_text():
    w = _Win()
    d = tl.TimelineDialog(w, messages=[{"role": "u", "text": "报表也做一下"}])
    item = d.list.item(0)
    d._jump(item)
    assert w.chat.textCursor().selectedText() != ""


def test_open_timeline_returns_dialog():
    w = _Win()
    assert isinstance(tl.open_timeline(w), tl.TimelineDialog)
