# -*- coding: utf-8 -*-
"""崩溃自动上报（core/auto_report）单元测试

不联网：只验"该不该发 / 标记有没有清 / 开关有没有生效"。
真正的发送在 test_notifier 里覆盖。
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import auto_report  # noqa: E402


def _mk(tmp_path, cfg=None):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "config.json").write_text(
        json.dumps(cfg if cfg is not None else {"auto_report_crash": True}),
        encoding="utf-8")
    return str(tmp_path)


def test_mark_and_clean_exit(tmp_path):
    base = _mk(tmp_path)
    assert auto_report.mark_running(base) is True
    assert os.path.exists(auto_report._marker(base))
    assert auto_report.mark_clean_exit(base) is True
    assert not os.path.exists(auto_report._marker(base))


def _write_dead_marker(base):
    marker = auto_report._marker(base)
    with open(marker, "w", encoding="utf-8") as f:
        json.dump({"pid": 2147483647, "start": "2026-01-01 00:00:00",
                   "version": "test"}, f)


def test_previous_crash_is_reported_and_marker_cleared(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    _write_dead_marker(base)
    seen = {}

    def fake_report(b, title, detail=""):
        seen["title"] = title
        seen["detail"] = detail
        return True, ""

    monkeypatch.setattr(auto_report, "report", fake_report)
    assert auto_report.check_previous_crash(base) is True
    assert "上次异常退出" in seen["title"]
    assert "没正常退出" in seen["detail"]
    assert not os.path.exists(auto_report._marker(base))


def test_live_pid_marker_is_not_a_crash(tmp_path, monkeypatch):
    """另一个实例仍在运行，不能把它的 .running 当成崩溃。"""
    base = _mk(tmp_path)
    auto_report.mark_running(base)          # 当前进程 pid，视为仍存活
    called = []
    monkeypatch.setattr(auto_report, "report",
                        lambda *a, **k: (called.append(1), (True, ""))[1])
    assert auto_report.check_previous_crash(base) is False
    assert not called
    assert os.path.exists(auto_report._marker(base))


def test_start_does_not_report_own_marker(tmp_path, monkeypatch):
    """回归：start() 不能把刚写的当前标记误报成上次异常退出。"""
    base = _mk(tmp_path)
    calls = []
    monkeypatch.setattr(auto_report, "_STARTED", False)
    monkeypatch.setattr(auto_report, "install", lambda b: None)
    monkeypatch.setattr(auto_report, "report",
                        lambda b, title, detail="": (
                            calls.append(title), (True, ""))[1])
    from core import crash_watchdog
    monkeypatch.setattr(crash_watchdog, "spawn", lambda b: False)
    assert auto_report.start(base) is True
    time.sleep(0.2)                         # 等后台补报线程跑一下
    assert calls == []
    assert os.path.exists(auto_report._marker(base))


def test_start_reports_stale_marker_before_writing_current(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    _write_dead_marker(base)
    calls = []
    monkeypatch.setattr(auto_report, "_STARTED", False)
    monkeypatch.setattr(auto_report, "install", lambda b: None)
    monkeypatch.setattr(auto_report, "report",
                        lambda b, title, detail="": (
                            calls.append((title, detail)), (True, ""))[1])
    from core import crash_watchdog
    monkeypatch.setattr(crash_watchdog, "spawn", lambda b: False)
    assert auto_report.start(base) is True
    time.sleep(0.2)
    assert calls and "上次异常退出" in calls[0][0]
    assert "2147483647" in calls[0][1]
    # 旧标记已处理，当前进程自己的标记必须保留
    assert os.path.exists(auto_report._marker(base))


def test_no_marker_means_no_report(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    called = []
    monkeypatch.setattr(auto_report, "report",
                        lambda *a, **k: (called.append(1), (True, ""))[1])
    assert auto_report.check_previous_crash(base) is False
    assert not called


def test_config_can_disable(tmp_path):
    base = _mk(tmp_path, {"auto_report_crash": False})
    assert auto_report.enabled(base) is False
    ok, err = auto_report.report(base, "t")
    assert ok is False
    assert "关闭" in err


def test_default_is_enabled(tmp_path):
    base = _mk(tmp_path, {})
    assert auto_report.enabled(base) is True


def test_can_report_rate_limits(tmp_path):
    base = _mk(tmp_path)
    assert auto_report._can_report(base) is True
    assert auto_report._can_report(base) is False      # 10 分钟内第二次


def test_report_without_channel(tmp_path):
    base = _mk(tmp_path, {"auto_report_crash": True})
    ok, err = auto_report.report(base, "t")
    assert ok is False
    assert "通道" in err


def test_install_wraps_excepthook(tmp_path):
    base = _mk(tmp_path)
    old = sys.excepthook
    try:
        auto_report.install(base)
        assert sys.excepthook is not old, "install 没装上钩子"
    finally:
        sys.excepthook = old
