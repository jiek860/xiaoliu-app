# -*- coding: utf-8 -*-
"""资源管理器筛选：通配符生成与模型接线。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from gui import explorer_filter as ef  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Model:
    def __init__(self):
        self.filters = None
        self.disables = None

    def setNameFilters(self, pats):
        self.filters = pats

    def setNameFilterDisables(self, on):
        self.disables = bool(on)


class _Tree:
    def __init__(self):
        self.expanded = 0

    def expandAll(self):
        self.expanded += 1


class _Dialog(QWidget):
    def __init__(self):
        super().__init__()
        self.fs_model = _Model()
        self.tree = _Tree()


def test_patterns_empty_and_words():
    assert ef.patterns("") == []
    assert ef.patterns("  ") == []
    assert ef.patterns("run") == ["*run*"]
    assert ef.patterns("a/b") == ["*b*"]


def test_apply_filter_empty_clears():
    m = _Model()
    assert ef.apply_filter(m, "") == []
    assert m.filters == []


def test_apply_filter_sets_hidden_mode():
    m = _Model()
    assert ef.apply_filter(m, "chat") == ["*chat*"]
    assert m.filters == ["*chat*"] and m.disables is False


def test_apply_filter_none_model():
    assert ef.apply_filter(None, "x") == []


def test_install_adds_box_and_filters():
    d = _Dialog()
    lay = QVBoxLayout(d)
    box = ef.install(d, lay)
    assert d.explorer_filter is box
    box.setText("trunk")
    assert d.fs_model.filters == ["*trunk*"]
    assert d.tree.expanded >= 1
    box.setText("")
    assert d.fs_model.filters == []
