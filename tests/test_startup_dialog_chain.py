# -*- coding: utf-8 -*-
"""Covers startup dialog serialization, login de-dup and editor paint guards."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def test_login_dialog_skips_agreement_when_parent_handled():
    """主窗口已确认协议时，登录框必须复用该状态、不再弹协议。"""
    src = open(os.path.join(BASE, "gui", "login_dialog.py"),
               encoding="utf-8").read()
    assert "_agreement_pending" in src, (
        "登录框必须读取父窗口的协议状态，否则会和主窗口重复弹协议")
    assert "parent_hint is not False" in src


def test_main_window_agreement_chain_methods_exist():
    from gui.main_window import JarvisWindow
    for name in ("_do_login_flow", "_confirm_agreement",
                 "_after_agreement_login", "_maybe_onboarding"):
        assert hasattr(JarvisWindow, name), name


def test_confirm_agreement_accepts_and_records(qapp, monkeypatch):
    from gui.main_window import JarvisWindow

    class W:
        trunk = type("T", (), {"_log": staticmethod(lambda *_: None)})()

        def __init__(self):
            self._agreement_pending = True
            self._agreement_confirmed = False

    w = W()
    import gui.agreement_dialog as ad

    class Dlg:
        agreed = True

        def __init__(self, *_a, **_k):
            pass

        def exec_(self):
            return 1

    monkeypatch.setattr(ad, "AgreementDialog", Dlg)
    assert JarvisWindow._confirm_agreement(w) is True
    assert w._agreement_pending is False
    assert w._agreement_confirmed is True


def test_confirm_agreement_rejection_returns_false(qapp, monkeypatch):
    from gui.main_window import JarvisWindow
    from PyQt5.QtWidgets import QMessageBox

    class W:
        trunk = type("T", (), {"_log": staticmethod(lambda *_: None)})()

        def __init__(self):
            self._agreement_pending = True

    import gui.agreement_dialog as ad

    class Dlg:
        agreed = False

        def __init__(self, *_a, **_k):
            pass

        def exec_(self):
            return 0

    monkeypatch.setattr(ad, "AgreementDialog", Dlg)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *_a, **_k: None))
    assert JarvisWindow._confirm_agreement(W()) is False


def test_confirm_agreement_broken_dialog_does_not_block_startup(qapp, monkeypatch):
    from gui.main_window import JarvisWindow

    class W:
        trunk = type("T", (), {"_log": staticmethod(lambda *_: None)})()

        def __init__(self):
            self._agreement_pending = True

    import gui.agreement_dialog as ad

    def boom(*_a, **_k):
        raise RuntimeError("no dialog")

    monkeypatch.setattr(ad, "AgreementDialog", boom)
    # 协议框打不开时不应把用户锁死
    assert JarvisWindow._confirm_agreement(W()) is True


def test_editor_paint_guard_swallows_painter_errors(qapp, monkeypatch):
    from PyQt5.QtGui import QPainter
    from gui.code_editor_widget import CodeEditWidget

    real = QPainter

    class BadPainter:
        def __init__(self, *_a, **_k):
            raise RuntimeError("painter unavailable")

    import gui.code_editor_widget as cew
    monkeypatch.setattr(cew, "QPainter", BadPainter)
    w = CodeEditWidget()
    try:
        w.setPlainText("a\nb")
        w.resize(200, 80)
        w.show()
        qapp.processEvents()          # 不能抛异常
    finally:
        w.close()
        monkeypatch.setattr(cew, "QPainter", real)
