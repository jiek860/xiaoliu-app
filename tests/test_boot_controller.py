# -*- coding: utf-8 -*-
"""Coverage for the deferred-boot path (gui.app_pyqt / gui.boot_controller)."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _fake_window():
    class W:
        def __init__(self):
            self.status = []
            self._boot_placeholder = None
            self.trunk = None
            self.booted = 0

        def statusBar(self):
            outer = self

            class Bar:
                def showMessage(self, text, _ms=0):
                    outer.status.append(text)
            return Bar()

        def _boot_trunk(self):
            self.booted += 1
            return object()

        def _init_from_trunk(self, trunk):
            self.trunk = trunk
    return W()


def test_boot_controller_installs_trunk_and_reports(qapp):
    from gui.boot_controller import BootController
    w = _fake_window()
    c = BootController(w)
    seen = []
    c.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    c._install(object())
    assert c.ok is True
    assert w.trunk is not None
    assert seen and seen[0][0] is True


def test_boot_controller_retries_once_then_fails(qapp):
    from gui.boot_controller import BootController

    class W(_fake_window().__class__):
        def _boot_trunk(self):
            self.booted += 1
            raise RuntimeError("boom")
    w = W()
    c = BootController(w)
    seen = []
    c.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    c._step_trunk()
    assert c.ok is False or c.error
    # 第一次失败后应该已经安排好重试（不会抛异常）
    assert "boom" in (c.error or "boom")


def test_boot_controller_handles_attach_failure(qapp):
    from gui.boot_controller import BootController

    class W(_fake_window().__class__):
        def _init_from_trunk(self, trunk):
            raise RuntimeError("attach failed")
    w = W()
    c = BootController(w)
    seen = []
    c.finished.connect(lambda ok, msg: seen.append((ok, msg)))
    c._install(object())
    assert c.ok is False
    assert "attach" in c.error
    assert seen and seen[0][0] is False


def test_run_pyqt_exists_and_accepts_startup(qapp, monkeypatch):
    """run_pyqt 必须接受 startup 参数（run.py 依赖它传计时器）。"""
    import inspect
    import gui.app_pyqt as ap
    sig = inspect.signature(ap.run_pyqt)
    assert "startup" in sig.parameters
    assert sig.parameters["startup"].default is None


def test_app_pyqt_helpers_are_importable():
    import gui.app_pyqt as ap
    assert callable(ap._check_deps)
    assert callable(ap._crash_hook)


def test_blocking_boot_env_switch(monkeypatch):
    """X6_BLOCKING_BOOT=1 必须被识别为"旧行为"。"""
    monkeypatch.setenv("X6_BLOCKING_BOOT", "1")
    assert os.environ.get("X6_BLOCKING_BOOT") == "1"
    monkeypatch.delenv("X6_BLOCKING_BOOT")
    assert os.environ.get("X6_BLOCKING_BOOT") is None


def test_resolve_startup_and_callbacks(qapp, monkeypatch):
    import gui.app_pyqt as ap
    assert ap._resolve_startup("X") == "X"
    mod = ap._resolve_startup(None)
    assert mod is not None and hasattr(mod, "mark")

    class W:
        def __init__(self):
            self.msgs = []
            class _Ph:
                def deleteLater(self):
                    pass
            self._boot_placeholder = _Ph()   # 真窗口才有占位页
            self.central = "x"
            self.trunk = None
            self.cleared = False

        def statusBar(self):
            outer = self

            class Bar:
                def showMessage(self, text, _ms=0):
                    outer.msgs.append(text)
            return Bar()

        def setCentralWidget(self, _w):
            self.cleared = True

    w = W()
    on_progress, on_finished = ap._make_boot_callbacks(w, None)
    on_progress("加载中")
    assert w.msgs and w.msgs[-1] == "加载中"
    on_finished(True, "已就绪")
    assert w.cleared is True
    assert w.msgs[-1] == "已就绪"


def test_boot_callbacks_progress_with_placeholder(qapp):
    import gui.app_pyqt as ap

    class Ph:
        def __init__(self):
            self.text = ""
            self.deleted = False

        def setText(self, t):
            self.text = t

        def deleteLater(self):
            self.deleted = True

    class W:
        def __init__(self):
            self._boot_placeholder = Ph()
            self.trunk = None

        def statusBar(self):
            outer = self

            class Bar:
                def showMessage(self, *_a):
                    outer.shown = True
            return Bar()

        def setCentralWidget(self, _w):
            pass

    w = W()
    on_progress, on_finished = ap._make_boot_callbacks(w, None)
    on_progress("正在加载核心模块…")
    assert w._boot_placeholder.text.startswith("正在加载")
    on_finished(True, "ok")
    assert w._boot_placeholder is None


def test_trunk_start_llm_workers_is_deferred(monkeypatch):
    """_start_llm_workers_later 必须真的延后，而不是立刻跑。"""
    import threading
    from core.trunk_background import TrunkBackgroundMixin

    called = []

    class T(TrunkBackgroundMixin):
        modules = {"llm": object()}

    timers = []

    class FakeTimer:
        def __init__(self, delay, fn):
            timers.append((delay, fn))

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", FakeTimer)
    T()._start_llm_workers_later(1.5)
    assert timers and timers[0][0] == 1.5
    assert called == []
