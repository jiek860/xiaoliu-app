# -*- coding: utf-8 -*-
"""主标签页 / 设置左分类的回归测试。"""
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
_APP = QApplication.instance() or QApplication([])


class Win(QWidget):
    def __init__(self):
        super().__init__()
        self.trunk = types.SimpleNamespace(base=BASE, config={}, modules={})


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


def test_refresh_status_meta_tolerates_deleted_widgets():
    """状态栏定时器回调不能去碰已经销毁的窗口/标签。

    2026-10-28 实测：这个 60 秒定时器的 lambda 在 pytest-qt 的 `_process_events`
    里踩到了上一个用例留下的已释放 QLabel，直接 access violation 把整个 pytest
    进程带走（faulthandler 记的是 `gui/chrome.py line ??? in <lambda>`）。
    """
    from PyQt5 import sip
    from PyQt5.QtWidgets import QStatusBar
    from gui.chrome import _alive, attach_status_meta, refresh_status_meta

    w = Win()
    attach_status_meta(w, QStatusBar(w))
    timer = w._status_meta_timer
    assert timer.isActive()
    refresh_status_meta(w, force=True)          # 正常路径照旧可用

    sip.delete(w.status_model_label)            # 模拟窗口销毁后残留的标签
    assert _alive(w.status_model_label) is False
    refresh_status_meta(w, force=True)          # 不能崩、不能抛
    timer.timeout.emit()                        # 定时器到点也只跳过这标签

    sip.delete(w)                               # 整个窗口都没了
    assert _alive(w) is False


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
