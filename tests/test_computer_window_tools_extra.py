# -*- coding: utf-8 -*-
"""窗口/UIA 工具：用假控件树覆盖枚举、查找、点击、输入和读值。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.computer_window_tools import ComputerWindowToolsMixin  # noqa: E402


class _Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class _Control:
    def __init__(self, name, ctype="PaneControl", children=None, value=""):
        self.Name = name
        self.ControlTypeName = ctype
        self.BoundingRectangle = _Rect(1, 2, 31, 42)
        self._children = list(children or [])
        self.clicked = False
        self.value = value

    def GetChildren(self):
        return list(self._children)

    def Click(self, **_kw):
        self.clicked = True

    def SetFocus(self):
        self.focused = True

    def GetValuePattern(self):
        outer = self

        class VP:
            Value = outer.value

            def SetValue(self, value):
                outer.value = value
        return VP()


class _Auto:
    def __init__(self, root):
        self.root = root

    def GetRootControl(self):
        return self.root


class _Dummy(ComputerWindowToolsMixin):
    def __init__(self, auto):
        self.auto = auto
        self.logs = []
        self.confirm = True
        self.typed = []

    def _uia(self):
        return self.auto

    def _log(self, action, detail="", *a, **k):
        self.logs.append((action, detail))

    def _confirm(self, *_a, **_k):
        return self.confirm

    def type_text(self, text):
        self.typed.append(text)


def _tree():
    button = _Control("保存", "ButtonControl")
    edit = _Control("输入框", "EditControl", value="旧值")
    root = _Control("桌面", "PaneControl", [button, edit])
    return _Dummy(_Auto(root)), button, edit


def test_ui_available_and_windows():
    d, _button, _edit = _tree()
    assert d.ui_available() is True
    r = d.ui_windows()
    assert r["ok"] is True
    assert r["窗口数"] >= 1


def test_ui_find_and_dump():
    d, _button, _edit = _tree()
    found = d.ui_find(name="保存", control_type="ButtonControl")
    assert found["ok"] and found["找到"] == 1
    dump = d.ui_dump(depth=2)
    assert dump["ok"] and "保存" in dump["结构"]


def test_ui_click_respects_confirmation():
    d, button, _edit = _tree()
    d.confirm = False
    assert d.ui_click("保存")["ok"] is False
    d.confirm = True
    assert d.ui_click("保存")["ok"] is True
    assert button.clicked is True


def test_ui_type_and_value():
    d, _button, edit = _tree()
    r = d.ui_type("输入框", "新值")
    assert r["ok"] is True
    assert edit.value == "新值"
    assert d.ui_value("输入框") == "新值"