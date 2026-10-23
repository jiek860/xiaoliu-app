# -*- coding: utf-8 -*-
"""活动栏 / 主标签页 / 设置左分类的回归测试。"""
import os
import sys
import types

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QListWidget, QTabWidget, QVBoxLayout, QWidget,
)
from PyQt5.QtCore import Qt  # noqa: E402
_APP = QApplication.instance() or QApplication([])


class Win(QWidget):
    def __init__(self):
        super().__init__()
        self.trunk = types.SimpleNamespace(base=BASE, config={}, modules={})
        self.clicked = None

    def _on_activity_clicked(self, item):
        self.clicked = item.data(Qt.UserRole)


def test_activity_bar_items_and_mode_visibility():
    from gui.chrome import build_activity_bar, set_activity_advanced_visible

    w = Win()
    bar = build_activity_bar(w)
    assert isinstance(bar, QListWidget)
    assert bar.count() == 7
    bar.itemClicked.emit(bar.item(0))
    assert w.clicked == "chat"
    set_activity_advanced_visible(w, False)
    hidden = [bar.isRowHidden(i) for i in range(bar.count())]
    assert hidden.count(True) == 3
    set_activity_advanced_visible(w, True)
    assert not any(bar.isRowHidden(i) for i in range(bar.count()))


def test_main_tabs_reuse_and_close_panel():
    from gui.chrome import build_main_tabs, close_panel_at, open_panel

    w = Win()
    tabs = build_main_tabs(w, QVBoxLayout())
    assert isinstance(tabs, QTabWidget)
    assert tabs.count() == 1
    assert tabs.tabText(0).endswith("对话")

    mod = types.ModuleType("test_fake_panel_mod")
    class DummyPanel(QWidget):
        def __init__(self, trunk, parent=None):
            super().__init__()
            self.setWindowTitle("Dummy")
    mod.DummyPanel = DummyPanel
    sys.modules["test_fake_panel_mod"] = mod
    try:
        p1 = open_panel(w, "dummy", "Dummy", "test_fake_panel_mod", "DummyPanel")
        p2 = open_panel(w, "dummy", "Dummy", "test_fake_panel_mod", "DummyPanel")
        assert p1 is p2
        assert tabs.count() == 2
        close_panel_at(w, 1)
        assert tabs.count() == 1
        p3 = open_panel(w, "dummy", "Dummy", "test_fake_panel_mod", "DummyPanel")
        assert p3 is not p1
        assert tabs.count() == 2
        close_panel_at(w, 0)  # 对话页不可关
        assert tabs.count() == 2
    finally:
        sys.modules.pop("test_fake_panel_mod", None)


def test_settings_left_category_is_synced(monkeypatch):
    from gui import settings_dialog as sd
    from gui import ui_mode

    made = []
    def fake_dlg(title="", w=0, h=0):
        d = QDialog()
        d.setWindowTitle(title or "设置")
        lay = QVBoxLayout(d)
        made.append(d)
        return d, lay

    monkeypatch.setattr(ui_mode, "get_ui_mode", lambda *a, **k: "advanced")
    old = QDialog.exec_
    QDialog.exec_ = lambda self: 0
    try:
        parent = Win()
        sd.show_settings_dialog(parent, fake_dlg, parent.trunk, BASE, "x6",
                                None, None, None, None, None, {})
        tabs = made[0].findChild(QTabWidget)
        nav = made[0].findChild(QListWidget, "settingsCategory")
        assert tabs is not None and nav is not None
        assert tabs.tabBar().isVisible() is False
        assert nav.count() == tabs.count() == 7
        nav.setCurrentRow(2)
        assert tabs.currentIndex() == 2
    finally:
        QDialog.exec_ = old
        for d in made:
            d.close()
