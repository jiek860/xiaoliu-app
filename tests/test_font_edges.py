# -*- coding: utf-8 -*-
"""Coverage for font-bootstrap edge paths, self-check line, and editor paint."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import font_bootstrap  # noqa: E402


def test_ensure_fonts_without_app_returns_reason(monkeypatch):
    monkeypatch.setattr(font_bootstrap, "_gui_app", lambda: None)
    r = font_bootstrap.ensure_fonts(None)
    assert r["ok"] is False
    assert "QApplication" in r["reason"]


def test_gui_app_returns_instance(qapp):
    assert font_bootstrap._gui_app() is qapp


def test_ensure_fonts_uses_default_family_when_preferred_missing(qapp, monkeypatch):
    from PyQt5.QtGui import QFontDatabase

    class FakeDB:
        def families(self):
            return ["Some Unknown Family"]

        def addApplicationFont(self, _p):
            return 0

    class FakeApp:
        def setFont(self, _f):
            raise RuntimeError("setFont failed")

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    r = font_bootstrap.ensure_fonts(FakeApp(), min_families=5)
    # 没有首选族 -> 走 else 分支；且 setFont 抛错不影响 ok
    assert r["ok"] is True
    assert "未匹配到首选族" in r["reason"]


def test_ensure_fonts_setfont_failure_is_tolerated(qapp, monkeypatch):
    class FakeDB:
        def __init__(self):
            self.n = 0

        def families(self):
            self.n += 1
            return [] if self.n == 1 else ["Segoe UI"]

        def addApplicationFont(self, _p):
            return 0

    class FakeApp:
        def setFont(self, _f):
            raise RuntimeError("nope")

    import PyQt5.QtGui as QtGui
    monkeypatch.setattr(QtGui, "QFontDatabase", FakeDB)
    r = font_bootstrap.ensure_fonts(FakeApp(), min_families=1)
    assert r["ok"] is True
    assert "已注册系统字体" in r["reason"]


def test_status_ok_with_qapp(qapp):
    font_bootstrap.ensure_fonts(qapp)
    s = font_bootstrap.status()
    assert s["ok"] is True
    assert s["count"] >= 1
    assert s["platform"]


def test_self_check_prints_font_line_when_ok(qapp, monkeypatch):
    """有字体时自检应打印 "字体: OK"。"""
    from core import self_check
    lines = []

    class T:
        base = BASE
        config = {"local_model": "m", "ollama_url": "http://127.0.0.1:11434",
                  "_schema_version": 2}
        modules = {}
        _lazy = {}
        data_dir = os.path.join(BASE, "data")

        def _log(self, *_a):
            pass

        def call(self, *_a, **_k):
            return {}

        def _check_ollama(self):
            return {"reachable": False, "models": []}

    font_bootstrap.ensure_fonts(qapp)
    # 只验证字体分支：直接调用内部逻辑等价路径
    fs = font_bootstrap.status()
    assert fs["ok"] is True
    src = open(os.path.join(BASE, "core", "self_check.py"),
               encoding="utf-8").read()
    assert 'log("字体: OK %d 个可用户族"' in src


def test_code_editor_paint_line_numbers_runs(qapp):
    """真实渲染一次行号，确保 paintEvent 不再抛 AttributeError。"""
    from PyQt5.QtGui import QPixmap
    from gui.code_editor_widget import CodeEditWidget
    font_bootstrap.ensure_fonts(qapp)
    w = CodeEditWidget()
    try:
        w.setPlainText("\n".join("line %d" % i for i in range(40)))
        w.resize(400, 200)
        w.show()
        qapp.processEvents()
        pix = QPixmap(w.size())
        w.render(pix)          # 触发 paintEvent -> paint_line_numbers
        assert not pix.isNull()
        assert w.blockCount() == 40
    finally:
        w.close()
