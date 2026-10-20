# -*- coding: utf-8 -*-
"""命令执行安全边界：应用启动、关机/重启、白名单和 shell=False。"""
import os
import shutil
import subprocess
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import command_policy  # noqa: E402
from modules.installed.computer_controller import ComputerController  # noqa: E402


class _FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {"电脑控制": True, "文件白名单": []}
        self.confirm_cb = None

    def rule(self, name, default=False):
        return default


def _controller(tmp_path):
    return ComputerController(_FakeTrunk(str(tmp_path)))


def test_command_policy_whitelist_and_meta_chars():
    assert command_policy.check_command("python -m pytest -q")[0] is True
    assert command_policy.check_command("ruff check .")[0] is True
    assert command_policy.check_command("calc.exe & whoami")[0] is False
    assert command_policy.check_command("randomcmd --x")[0] is False
    assert command_policy.has_shell_meta("a > b") == ">"


def test_app_launch_uses_argv_not_shell(tmp_path, monkeypatch):
    exe = tmp_path / "notepad.exe"
    exe.write_bytes(b"MZ")
    c = _controller(tmp_path)
    monkeypatch.setattr(c, "_search_startmenu", lambda _app: (None, 0))
    monkeypatch.setattr(shutil, "which",
                        lambda name: str(exe) if name == "notepad.exe" else None)
    calls = []
    monkeypatch.setattr("core.computer_app_tools.subprocess.Popen",
                        lambda *a, **k: calls.append((a, k)))
    ok, _msg = c.open_app("notepad.exe")
    assert ok is True
    assert calls
    args, kwargs = calls[0]
    assert args[0] == [str(exe)]
    assert kwargs.get("shell") is False


def test_app_launch_rejects_shell_metacharacters(tmp_path, monkeypatch):
    exe = tmp_path / "calc.exe"
    exe.write_bytes(b"MZ")
    c = _controller(tmp_path)
    calls = []
    monkeypatch.setattr("core.computer_app_tools.subprocess.Popen",
                        lambda *a, **k: calls.append((a, k)))
    ok, msg = c._launch_app_target(str(exe) + " & whoami", "calc.exe")
    assert ok is False
    assert "非法字符" in msg
    assert not calls


def test_shutdown_restart_cancel_use_argv(tmp_path, monkeypatch):
    c = _controller(tmp_path)
    monkeypatch.setattr(c, "_danger_enabled", lambda _name: True)
    monkeypatch.setattr(c, "_confirm", lambda *a, **k: True)
    calls = []
    monkeypatch.setattr("core.computer_system_tools.subprocess.Popen",
                        lambda *a, **k: calls.append((a, k)))
    assert c.shutdown(30)[0] is True
    assert c.restart(0)[0] is True
    assert c.cancel_shutdown()[0] is True
    assert calls[0][0][0] == ["shutdown", "/s", "/t", "30"]
    assert calls[1][0][0] == ["shutdown", "/r", "/t", "0"]
    assert calls[2][0][0] == ["shutdown", "/a"]
    assert all(k.get("shell") is False for _a, k in calls)


def test_shell_rejects_metachar_before_execution(tmp_path, monkeypatch):
    c = _controller(tmp_path)
    monkeypatch.setattr(c, "_shell_enabled", lambda: True)
    calls = []
    monkeypatch.setattr("core.computer_system_tools.subprocess.run",
                        lambda *a, **k: calls.append((a, k)))
    r = c.shell("dir & whoami")
    assert r["ok"] is False
    assert "不允许串联" in r["错误"]
    assert not calls


def test_shell_runs_without_python_shell_true(tmp_path, monkeypatch):
    c = _controller(tmp_path)
    monkeypatch.setattr(c, "_shell_enabled", lambda: True)
    monkeypatch.setattr(c, "_authorize_shell", lambda _cmd: (True, ""))
    calls = []

    class Result:
        stdout = "ok"
        stderr = ""
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Result()

    monkeypatch.setattr("core.computer_system_tools.subprocess.run", fake_run)
    r = c.shell("dir")
    assert r["ok"] is True
    argv, kwargs = calls[0]
    assert kwargs.get("shell") is False
    assert isinstance(argv, (list, str))
    if isinstance(argv, list):
        assert argv[0].lower().endswith(("cmd.exe", "comspec"))
    else:
        assert "cmd.exe" in argv.lower()

def test_build_exec_argv_direct_python_and_cmd_wrapper(tmp_path):
    import sys
    direct, wrapped = command_policy.build_exec_argv(
        '"%s" -c "print(1)"' % sys.executable)
    assert wrapped is False
    assert isinstance(direct, list)
    assert direct[0].lower().endswith("python.exe")

    script = tmp_path / "hello.cmd"
    script.write_text("@echo off\necho hello\n", encoding="utf-8")
    argv, wrapped = command_policy.build_exec_argv('"%s"' % script)
    assert wrapped is True
    assert isinstance(argv, str)
    assert "cmd.exe" in argv.lower()


def test_mcp_stdio_popen_args_avoids_shell_true():
    from core.mcp_stdio import StdioMCPServer
    srv = StdioMCPServer("demo", "echo hello")
    args, used_shell = srv._popen_args()
    assert used_shell is False
    assert args
    # 元字符命令必须被策略拦住
    srv2 = StdioMCPServer("bad", "echo hi & whoami")
    try:
        srv2._popen_args()
    except ValueError as e:
        assert "策略" in str(e)
    else:
        raise AssertionError("MCP 元字符命令没有被拒绝")
