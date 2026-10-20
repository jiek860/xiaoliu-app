# -*- coding: utf-8 -*-
"""run.py startup marks and watchdog ordering (static + behaviour)."""
import ast
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def _run_src():
    return open(os.path.join(BASE, "run.py"), encoding="utf-8").read()


def test_run_marks_process_start_first():
    src = _run_src()
    assert 'startup.mark("进程启动")' in src
    # 必须在 crash_guard 之前
    assert src.index('startup.mark("进程启动")') < src.index("crash_guard")


def test_watchdog_starts_before_gui_import():
    src = _run_src()
    i_wd = src.index("auto_report.start(")
    i_gui = src.index("from gui.app_pyqt import run_pyqt")
    assert i_wd < i_gui, "看门狗必须在导入 GUI 之前拉起"


def test_run_passes_startup_to_gui():
    src = _run_src()
    assert "run_pyqt(startup=" in src


def test_watchdog_mode_exits_without_qt():
    src = _run_src()
    assert '--watchdog' in src
    i = src.index("--watchdog")
    assert "crash_watchdog" in src[i:i + 900]


def test_run_is_valid_python():
    ast.parse(_run_src())
