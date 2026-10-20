# -*- coding: utf-8 -*-
"""闪退看门狗（core/crash_watchdog）单元测试

不真的拉起子进程：只验"参数解析 / 该不该报 / 报完有没有清标记"。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import auto_report  # noqa: E402
from core import crash_watchdog as wd  # noqa: E402


def _mk(tmp_path, cfg=None):
    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "config.json").write_text(
        json.dumps(cfg if cfg is not None else {"crash_watchdog": True}),
        encoding="utf-8")
    return str(tmp_path)


def test_parse_args():
    assert wd.parse_args(["run.py", "--watchdog", "123"]) == 123
    assert wd.parse_args(["run.py"]) is None
    assert wd.parse_args(["--watchdog"]) is None
    assert wd.parse_args(["--watchdog", "abc"]) is None


def test_main_invalid_args():
    assert wd.main(["run.py"]) == 2


def test_enabled_default_true(tmp_path):
    assert wd._enabled(_mk(tmp_path, {})) is True


def test_enabled_can_be_disabled(tmp_path):
    assert wd._enabled(_mk(tmp_path, {"crash_watchdog": False})) is False


def test_spawn_skips_when_disabled(tmp_path):
    base = _mk(tmp_path, {"crash_watchdog": False})
    assert wd.spawn(base) is False


def test_spawn_cmd_has_watchdog_flag():
    cmd = wd._spawn_cmd()
    assert cmd, "_spawn_cmd 没返回命令"
    assert "--watchdog" in cmd


def test_handle_exit_reports_when_marker_matches(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    auto_report.mark_running(base)          # 写入 .running（当前进程 pid）
    seen = {}

    def fake_report(b, title, detail=""):
        seen["title"] = title
        seen["detail"] = detail
        return True, ""

    monkeypatch.setattr(auto_report, "report", fake_report)
    ok = wd._handle_exit(os.getpid(), base)
    assert ok is True
    assert "看门狗" in seen["title"]
    assert str(os.getpid()) in seen["detail"]
    assert not os.path.exists(wd._running_path(base)), "报完要清掉标记"


def test_handle_exit_no_report_when_marker_missing(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    called = []
    monkeypatch.setattr(auto_report, "report",
                        lambda *a, **k: (called.append(1), (True, ""))[1])
    assert wd._handle_exit(12345, base) is True
    assert not called


def test_handle_exit_no_report_when_pid_differs(tmp_path, monkeypatch):
    base = _mk(tmp_path)
    auto_report.mark_running(base)          # 标记里是当前 pid
    called = []
    monkeypatch.setattr(auto_report, "report",
                        lambda *a, **k: (called.append(1), (True, ""))[1])
    assert wd._handle_exit(999999, base) is True
    assert not called
