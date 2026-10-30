# -*- coding: utf-8 -*-
"""工作台 -> AI 上下文：选区/整文件、面板展开与快捷键。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import (QApplication, QDockWidget, QPlainTextEdit,  # noqa: E402
                             QWidget)
from PyQt5.QtGui import QTextCursor  # noqa: E402

from gui import workbench_context as wc  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Edit(QPlainTextEdit):
    def __init__(self, filepath=""):
        super().__init__()
        self.filepath = filepath


class _Tabs:
    def __init__(self, widget):
        self._w = widget

    def currentWidget(self):
        return self._w


class _Dock(QWidget):
    def __init__(self):
        super().__init__()
        self.goal = QPlainTextEdit()
        self.ai_host = QDockWidget("AI")
        self.ai_host.setWidget(QWidget())


class _Dialog(QWidget):
    def __init__(self, widget=None, with_dock=False):
        super().__init__()
        self.root = BASE
        self.tabs = _Tabs(widget) if widget is not None else None
        self.status = []
        self.ai_dock = _Dock() if with_dock else None

    def _status(self, text, timeout=0):
        self.status.append(text)


def test_collect_full_file():
    f = os.path.join(BASE, "core", "trunk.py")
    w = _Edit(f)
    w.setPlainText(open(f, encoding="utf-8").read())
    d = _Dialog(w)
    text = wc.collect(d)
    assert "文件 core/trunk.py" in text and "```python" in text


def test_collect_selection_uses_line_header():
    f = os.path.join(BASE, "core", "trunk.py")
    w = _Edit(f)
    w.setPlainText("a = 1\nb = 2\nc = 3")
    cur = w.textCursor()
    cur.movePosition(QTextCursor.Down)
    cur.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
    w.setTextCursor(cur)
    d = _Dialog(w)
    text = wc.collect(d)
    assert text.startswith("片段 core/trunk.py:2")


def test_collect_without_widget_is_empty():
    d = _Dialog(None)
    assert wc.collect(d) == ""


def test_send_to_ai_fills_goal_and_reports():
    f = os.path.join(BASE, "core", "trunk.py")
    w = _Edit(f)
    w.setPlainText("x = 1")
    d = _Dialog(w, with_dock=True)
    n = wc.send_to_ai(d)
    assert n > 0
    assert "x = 1" in d.ai_dock.goal.toPlainText()
    assert any("加入 AI 提示" in s for s in d.status)


def test_send_to_ai_without_context_reports():
    d = _Dialog(_Edit(""), with_dock=True)
    d.ai_dock.goal.setPlainText("")
    # 未保存且没有任何文字的标签：collect 返回空串
    assert wc.send_to_ai(d) == 0
    assert any("没有可发送" in s for s in d.status)


def test_send_to_ai_without_dock_reports():
    w = _Edit("")
    w.setPlainText("x = 1")
    d = _Dialog(w, with_dock=False)
    assert wc.send_to_ai(d) == 0
    assert any("AI 面板不可用" in s for s in d.status)


def test_install_adds_shortcut():
    d = _Dialog(_Edit(""), with_dock=True)
    sc = wc.install(d)
    assert sc is not None and d.send_context_shortcut is sc
