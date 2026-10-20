# -*- coding: utf-8 -*-
"""窗口布局记忆：位置、大小、最大化状态。"""
from __future__ import annotations

from PyQt5.QtCore import QByteArray
from PyQt5.QtWidgets import QApplication

from gui.ui_mode import load_ui_state, save_ui_state


class WindowStateManager:
    def __init__(self, base: str):
        self.base = base
        self._state = load_ui_state(base)
        self._window = self._state.setdefault("window", {})

    def restore(self, win) -> bool:
        raw = str(self._window.get("geometry_b64") or "")
        restored = False
        if raw:
            try:
                geom = QByteArray.fromBase64(raw.encode("ascii"))
                restored = bool(win.restoreGeometry(geom))
            except Exception:  # 静默是故意的
                restored = False
        if not restored:
            self._center_on_primary(win)
        if self._window.get("maximized"):
            try:
                win.showMaximized()
            except Exception:  # 静默是故意的
                pass
        self._ensure_visible(win)
        return restored

    def save(self, win) -> dict:
        try:
            geom = bytes(win.saveGeometry().toBase64()).decode("ascii")
            self._window["geometry_b64"] = geom
        except Exception:  # 静默是故意的
            pass
        try:
            self._window["maximized"] = bool(win.isMaximized())
        except Exception:  # 静默是故意的
            pass
        self._state["window"] = self._window
        self._state = save_ui_state(self.base, self._state)
        return dict(self._window)

    def reset(self) -> dict:
        self._window = {}
        self._state["window"] = {}
        self._state = save_ui_state(self.base, self._state)
        return {}

    def _center_on_primary(self, win):
        try:
            app = QApplication.instance()
            screen = app.primaryScreen() if app else None
            if not screen:
                return
            area = screen.availableGeometry()
            w = min(1280, max(900, area.width() - 120))
            h = min(860, max(640, area.height() - 120))
            win.resize(w, h)
            win.move(area.x() + (area.width() - w) // 2,
                     area.y() + (area.height() - h) // 2)
        except Exception:  # 静默是故意的
            pass

    def _ensure_visible(self, win):
        try:
            app = QApplication.instance()
            if not app:
                return
            frame = win.frameGeometry()
            for screen in app.screens():
                if screen.availableGeometry().intersects(frame):
                    return
            self._center_on_primary(win)
        except Exception:  # 静默是故意的
            pass
