# -*- coding: utf-8 -*-
"""Covers run_pyqt's font-bootstrap wiring without entering a real event loop."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _patch(monkeypatch, calls, exec_returns=0):
    import PyQt5.QtWidgets as W
    import PyQt5.QtCore as C
    import gui.main_window as mw
    import gui.boot_controller as bc

    class FakeApp:
        _real = W.QApplication

        @staticmethod
        def setAttribute(*_a):
            pass

        @classmethod
        def instance(cls):
            # pytest-qt 在收尾时也会调 instance()，必须转发给真实 QApplication
            return cls._real.instance()

        def __init__(self, *_a):
            calls["app"] = True

        def setApplicationName(self, *_a):
            pass

        def setFont(self, *_a):
            pass

        def exec_(self):
            calls["exec"] = True
            return exec_returns

    class FakeWindow:
        def __init__(self, startup=None, boot_signal=True):
            calls["boot_signal"] = boot_signal
            self.trunk = None
            self._boot_placeholder = None

        def show(self):
            calls["show"] = True

        def statusBar(self):
            class B:
                def showMessage(self, *_a):
                    pass
            return B()

        def setCentralWidget(self, *_a):
            pass

    class Sig:
        def connect(self, *_a):
            pass

    class FakeBoot:
        def __init__(self, window, startup=None):
            self.progress = Sig()
            self.finished = Sig()
            calls["boot_created"] = True

        def start(self, delay_ms=0):
            calls["boot_started"] = True

    monkeypatch.setattr(W, "QApplication", FakeApp, raising=False)
    # run_pyqt 里是 `from PyQt5.QtWidgets import QApplication`，所以必须替换模块属性
    monkeypatch.setattr(mw, "JarvisWindow", FakeWindow)
    monkeypatch.setattr(bc, "BootController", FakeBoot)
    # Qt 常量只需存在
    for name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        if not hasattr(C.Qt, name):
            monkeypatch.setattr(C.Qt, name, 0, raising=False)


def test_run_pyqt_calls_font_bootstrap_and_boot_controller(monkeypatch):
    import gui.app_pyqt as ap

    calls = {}
    _patch(monkeypatch, calls)
    monkeypatch.setattr("core.font_bootstrap.ensure_fonts",
                        lambda _a: calls.__setitem__("fonts", True) or
                        {"ok": True, "after": 7, "reason": ""})
    monkeypatch.setattr(ap, "_resolve_startup", lambda s: None)
    monkeypatch.delenv("X6_BLOCKING_BOOT", raising=False)

    try:
        ap.run_pyqt()
    except SystemExit:
        pass

    assert calls.get("fonts") is True, "run_pyqt 必须调用字体自愈"
    assert calls.get("app") is True
    assert calls.get("show") is True
    assert calls.get("boot_started") is True
    assert calls.get("boot_signal") is False


def test_run_pyqt_blocking_mode_skips_boot_controller(monkeypatch):
    import gui.app_pyqt as ap

    calls = {}
    _patch(monkeypatch, calls)
    monkeypatch.setattr("core.font_bootstrap.ensure_fonts",
                        lambda _a: {"ok": True, "after": 1, "reason": ""})
    monkeypatch.setattr(ap, "_resolve_startup", lambda s: None)
    monkeypatch.setenv("X6_BLOCKING_BOOT", "1")

    try:
        ap.run_pyqt()
    except SystemExit:
        pass

    assert calls.get("boot_signal") is True
    assert "boot_started" not in calls


def test_run_pyqt_tolerates_font_failure(monkeypatch):
    import gui.app_pyqt as ap

    calls = {}
    _patch(monkeypatch, calls)

    def boom(_a):
        raise RuntimeError("font subsystem down")

    monkeypatch.setattr("core.font_bootstrap.ensure_fonts", boom)
    monkeypatch.setattr(ap, "_resolve_startup", lambda s: None)
    monkeypatch.delenv("X6_BLOCKING_BOOT", raising=False)

    try:
        ap.run_pyqt()
    except SystemExit:
        pass
    # 字体挂了也要把界面显示出来
    assert calls.get("show") is True
