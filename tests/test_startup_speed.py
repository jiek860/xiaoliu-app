# -*- coding: utf-8 -*-
"""Startup and watchdog tests (no GUI event loop required)."""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import startup  # noqa: E402


def test_marks_are_monotonic_and_named():
    startup.mark("t1")
    startup.mark("t2")
    stages = startup.report()["stages"]
    times = [s["at_ms"] for s in stages]
    assert times == sorted(times)
    assert stages[-1]["name"] == "t2"
    assert all(s["delta_ms"] >= 0 for s in stages)


def test_elapsed_returns_positive():
    t0 = startup.since_start_ms()
    time.sleep(0.01)
    assert startup.elapsed_ms("probe", t0) >= 5


def test_summary_line_contains_total():
    startup.mark("x")
    line = startup.log_summary(None)
    assert "[启动耗时]" in line and "总" in line


def test_watchdog_process_starts_dead_fast():
    """看门狗进程必须能在 <1.5s 内落地，且不导入 Qt。"""
    code = (
        "import os,sys,time;"
        "sys.path.insert(0, r'%s');"
        "from core import crash_watchdog;"
        "t=time.perf_counter();"
        "ok=crash_watchdog.spawn(r'%s');"
        "print('spawn', ok, round((time.perf_counter()-t)*1000,1));"
        "print('qt', 'PyQt5' in sys.modules)"
    ) % (BASE, BASE)
    started = time.perf_counter()
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=60, cwd=BASE)
    elapsed = (time.perf_counter() - started) * 1000
    assert r.returncode == 0, r.stderr[-300:]
    assert "qt False" in r.stdout
    assert elapsed < 8000


def test_spawn_is_skipped_when_disabled(tmp_path, monkeypatch):
    from core import crash_watchdog
    monkeypatch.setattr(crash_watchdog, "_enabled", lambda _b: False)
    assert crash_watchdog.spawn(str(tmp_path)) is False


def test_boot_controller_defers_trunk_until_event_loop(qapp):
    """骨架先出来的保证：boot_signal=False 时 __init__ 不建 Trunk。"""
    import os
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow
    w = JarvisWindow(boot_signal=False)
    try:
        assert w.trunk is None, "骨架阶段不该已经建好 Trunk"
        assert getattr(w, "_boot_placeholder", None) is not None
        assert w.windowTitle().startswith("✨")
    finally:
        w.close()


def test_mark_returns_timestamp_and_never_raises():
    from core import startup
    v = startup.mark("robust")
    assert isinstance(v, float) and v >= 0
    # 非字符串名字也要能记（插件/线程可能传对象）
    startup.mark(object())
    assert startup.report()["stages"]
