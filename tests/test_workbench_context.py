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


class _StartDock(_Dock):
    """记录 start() 次数，验证「重构/补测试直接开跑」。"""

    def __init__(self):
        super().__init__()
        self.started = 0

    def start(self):
        self.started += 1


class _Dialog(QWidget):
    def __init__(self, widget=None, with_dock=False, dock=None):
        super().__init__()
        self.root = BASE
        self.tabs = _Tabs(widget) if widget is not None else None
        self.status = []
        self.ai_dock = dock if dock is not None else (
            _Dock() if with_dock else None)

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
    assert getattr(d, "ai_quick_bar", None) is None   # 没有 _editor，浮条降级


# ---------------- 批次 D10：编辑器快捷动作 ----------------
def test_send_action_explain_fills_without_starting():
    f = os.path.join(BASE, "core", "trunk.py")
    w = _Edit(f)
    w.setPlainText("def foo():\n    return 1")
    dock = _StartDock()
    d = _Dialog(w, dock=dock)
    n = wc.send_action(d, "explain")
    assert n > 0
    assert "解释这段代码" in dock.goal.toPlainText()
    assert dock.started == 0


def test_send_action_refactor_starts_agent():
    f = os.path.join(BASE, "core", "trunk.py")
    w = _Edit(f)
    w.setPlainText("x = 1")
    dock = _StartDock()
    d = _Dialog(w, dock=dock)
    n = wc.send_action(d, "refactor")
    assert n > 0
    assert "重构这段代码" in dock.goal.toPlainText()
    assert dock.started == 1


def test_send_action_keeps_existing_goal():
    w = _Edit("")
    w.setPlainText("x = 1")
    dock = _StartDock()
    dock.goal.setPlainText("先问一句")
    d = _Dialog(w, dock=dock)
    wc.send_action(d, "test")
    assert "先问一句" in dock.goal.toPlainText()
    assert "pytest" in dock.goal.toPlainText()


def test_send_action_unknown_or_without_dock_is_zero():
    d = _Dialog(_Edit(""), with_dock=False)
    assert wc.send_action(d, "nope") == 0
    assert wc.send_action(d, "explain") == 0
    assert any("AI 面板不可用" in s for s in d.status)
