# -*- coding: utf-8 -*-
"""后台运行时治理测试（关闭窗口后线程/定时器必须收干净）。"""

import ast
import os
import sys
import threading

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------- 静态：不留非 daemon 线程 ----------------
def test_no_nondaemon_timer():
    """threading.Timer 默认 daemon=False，会让进程退出时挂住。"""
    bad = []
    for root in ("core", "gui", "modules"):
        for dirpath, _dirs, files in os.walk(os.path.join(BASE, root)):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                src = open(path, encoding="utf-8", errors="replace").read()
                if "threading.Timer" not in src:
                    continue
                tree = ast.parse(src)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    f = node.func
                    if not (isinstance(f, ast.Attribute) and f.attr == "Timer"):
                        continue
                    # 允许两种情况之一：
                    #  a) 先赋值再 .daemon = True
                    #  b) 同一语句里没有直接 .start()（交给别处设置 daemon）
                    seg = ast.unparse(node)
                    if ".start()" in seg:
                        bad.append("%s:%d" % (os.path.relpath(path, BASE),
                                              node.lineno))
    assert not bad, "Timer 未设 daemon 就直接 start(): %s" % bad


def test_main_window_has_close_event():
    """主窗口必须有 closeEvent 停定时器。"""
    src = open(os.path.join(BASE, "gui", "main_window.py"),
               encoding="utf-8").read()
    assert "def closeEvent" in src
    assert "_activity_timer" in src
    assert "_proactive_timer" in src
    assert "_status_timer" in src


# ---------------- 运行时：真实构建/关闭 ----------------
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_timers_stop_after_close(app):
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    try:
        w.show()
        for _ in range(10):
            app.processEvents()
        names = ("_activity_timer", "_proactive_timer", "_status_timer")
        timers = [getattr(w, n, None) for n in names]
        before = sum(1 for t in timers if t is not None and t.isActive())
        assert before > 0, "启动后应有活跃定时器"
        w.close()
        for _ in range(10):
            app.processEvents()
        after = sum(1 for t in timers if t is not None and t.isActive())
        assert after == 0, "关闭后仍有 %d 个定时器在跑" % after
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass


def test_no_nondaemon_threads_after_build(app):
    """构建主窗口后不应留下非 daemon 线程（否则进程退不出）。"""
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    try:
        w.show()
        for _ in range(10):
            app.processEvents()
        # 排除测试框架自身的线程（pytest-timeout 等），那是 CI 环境带来的，
        # 不是被测程序创建的。
        framework = ("MainThread", "pytest_timeout")
        leftover = [t.name for t in threading.enumerate()
                    if not t.daemon and not t.name.startswith(framework)]
        assert not leftover, "存在非 daemon 线程: %s" % leftover
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass


def test_close_event_calls_trunk_shutdown(app):
    """关闭窗口必须通知 trunk 收尾（存配置/停子进程）。"""
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    calls = []
    original = getattr(w.trunk, "shutdown", None)
    w.trunk.shutdown = lambda: calls.append(1)
    try:
        w.show()
        w.close()
        assert calls, "closeEvent 没有调用 trunk.shutdown()"
    finally:
        if original is not None:
            w.trunk.shutdown = original


def test_llm_watchdog_thread_can_be_stopped():
    """`llm-watchdog` 原来是 while True 无出口，stop() 必须真能把它收掉。

    实测（2026-10-28）：全量测试跑到后段残留 5 个 llm-watchdog，
    加上每个 Trunk 的 3 个常驻线程 → 129 个线程，最后几条用例挂在
    "can't start new thread" / "页面文件太小" 上。
    """
    from core.llm_client import LLMClient
    llm = LLMClient(defer_warmup=True)
    assert llm.start_background_workers() is True
    t = llm._timer
    try:
        assert t.is_alive()
    finally:
        llm.stop()
    t.join(timeout=3)
    assert not t.is_alive(), "stop() 之后看门狗线程还在跑"
    # 幂等：再停一次不该抛
    llm.stop()
