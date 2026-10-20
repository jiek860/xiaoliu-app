# -*- coding: utf-8 -*-
"""主题、字号、密度管理：持久化在 data/ui_state.json。"""
from __future__ import annotations

import json
import os
import threading

from PyQt5.QtWidgets import QApplication

from gui.style import STYLE
from gui.ui_mode import load_ui_state, save_ui_state

_LOCK = threading.RLock()

DEFAULT_APPEARANCE = {
    "theme": "system",       # system / light / dark
    "accent": "blue",
    "font_size": 14,
    "density": "comfortable",
    "code_font": "Consolas",
}

THEME_LABELS = {"system": "跟随系统", "light": "浅色", "dark": "深色"}
DENSITY_LABELS = {"compact": "紧凑", "comfortable": "舒适", "spacious": "宽松"}


def _system_is_dark() -> bool:
    try:
        app = QApplication.instance()
        if app is None:
            return False
        pal = app.palette()
        c = pal.window().color()
        return (c.red() + c.green() + c.blue()) < 3 * 128
    except Exception:  # 静默是故意的
        return False


class ThemeManager:
    def __init__(self, base: str):
        self.base = base
        self._state = load_ui_state(base)
        app = self._state.setdefault("appearance", {})
        for k, v in DEFAULT_APPEARANCE.items():
            app.setdefault(k, v)
        self._appearance = app

    @property
    def appearance(self):
        return dict(self._appearance)

    def effective_theme(self) -> str:
        t = str(self._appearance.get("theme", "system"))
        if t not in ("light", "dark"):
            return "dark" if _system_is_dark() else "light"
        return t

    def set_options(self, **kwargs):
        for k in DEFAULT_APPEARANCE:
            if k in kwargs:
                self._appearance[k] = kwargs[k]
        self._state["appearance"] = self._appearance
        self._state = save_ui_state(self.base, self._state)
        self._appearance = self._state["appearance"]
        return self.appearance

    def reset(self):
        self._appearance = dict(DEFAULT_APPEARANCE)
        self._state["appearance"] = self._appearance
        self._state = save_ui_state(self.base, self._state)
        return self.appearance

    def stylesheet(self) -> str:
        fs = int(self._appearance.get("font_size", 14) or 14)
        density = str(self._appearance.get("density", "comfortable"))
        pad = {"compact": "7px", "comfortable": "10px", "spacious": "13px"}.get(
            density, "10px")
        if self.effective_theme() == "dark":
            qss = STYLE + """
QMainWindow, QWidget { background: #171a21; color: #e6e8ee; }
QLabel { color: #e6e8ee; }
QPushButton { background: #232838; color: #e6e8ee; border-color: #343b4d; padding: %s; }
QPushButton:hover { background: #2d3448; border-color: #5b8def; color: #9ec1ff; }
QTextBrowser, QListWidget, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit {
    background: #1d2230; color: #e6e8ee; border-color: #343b4d;
}
QMenu, QDialog, QScrollArea { background: #1d2230; color: #e6e8ee; }
QTabWidget::pane { border-color: #343b4d; }
QHeaderView::section { background: #232838; color: #e6e8ee; border-color: #343b4d; }
QWidget { font-size: %dpx; }
""" % (pad, fs)
        else:
            qss = STYLE + """
QPushButton { padding: %s; }
QWidget { font-size: %dpx; }
""" % (pad, fs)
        return qss

    def apply_to(self, window):
        window.setStyleSheet(self.stylesheet())
        return self.stylesheet()


def get_theme_manager(base: str) -> ThemeManager:
    return ThemeManager(base)
