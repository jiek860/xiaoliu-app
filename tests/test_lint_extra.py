# -*- coding: utf-8 -*-
"""批次 D9：附加静态检查（ruff/mypy）与失败定位进回修提示。"""
import os
import sys
import threading

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code_agent import CodeAgent  # noqa: E402
from core.code_command_runner import CodeCommandRunnerMixin  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None, base="."):
        self.rules = rules or {}
        self.base = base
        self.config = {}

    def rule(self, name, default=None):
        return self.rules.get(name, default)


class Host(CodeCommandRunnerMixin):
    """只跑 lint 的最小宿主：命令执行被替换掉，不真的起进程。"""

    def __init__(self, root, rules=None):
        self.root = str(root)
        self.trunk = FakeTrunk(rules, str(root))
        self.lint_commands = []
        self.calls = []
        self._cancel = threading.Event()
        self._proc_lock = threading.Lock()
        self._active_proc = None

    def _check_control(self):
        return None

    def _kill_active_proc(self):
        return None

    def _run_command(self, cmd, timeout=180, sandboxed=False):
        self.calls.append(cmd)
        return {"ok": False, "exit_code": 1, "output": "boom"}


def test_shadow_records_extra_without_failing(tmp_path, monkeypatch):
    """默认 shadow：ruff 的错只记录（advisory），任务仍算完成。"""
    (tmp_path / "tests").mkdir()
    host = Host(tmp_path)
    monkeypatch.setattr(host, "_module_installed",
                        staticmethod(lambda name: name == "ruff"))
    result = host.run_lint()
    assert result["ok"] is True
    ruff = [x for x in result["results"] if "ruff" in x["command"]]
    assert ruff and ruff[0]["advisory"] is True
    assert result["skipped_modules"] == ["mypy"]


def test_on_mode_extra_blocks_completion(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    host = Host(tmp_path, {"code.lint_extra": "on"})
    monkeypatch.setattr(host, "_module_installed",
                        staticmethod(lambda name: name == "ruff"))
    result = host.run_lint()
    assert result["ok"] is False
    assert not [x for x in result["results"] if x.get("advisory")]


def test_off_mode_skips_extras(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    host = Host(tmp_path, {"code.lint_extra": "off"})
    monkeypatch.setattr(host, "_module_installed",
                        staticmethod(lambda name: True))
    result = host.run_lint()
    assert result["ok"] is True
    assert result["results"] == []
    assert result["skipped_modules"] == ["ruff", "mypy"]


def test_explicit_commands_do_not_add_extras(tmp_path, monkeypatch):
    host = Host(tmp_path)
    monkeypatch.setattr(host, "_module_installed",
                        staticmethod(lambda name: True))
    result = host.run_lint(["echo lint"])
    assert [x["command"] for x in result["results"]] == ["echo lint"]
    assert result["skipped_modules"] == []


def test_non_python_project_skips_extras(tmp_path, monkeypatch):
    host = Host(tmp_path)
    monkeypatch.setattr(host, "_module_installed",
                        staticmethod(lambda name: True))
    result = host.run_lint()
    assert result["results"] == []
    assert result["skipped_modules"] == ["ruff", "mypy"]


def test_failure_digest_includes_located_symbol(tmp_path):
    """失败定位默认 on：回修提示里直接写「文件:行（函数）」。"""
    core = tmp_path / "core"
    core.mkdir()
    (core / "m.py").write_text(
        "def outer():\n    pass\n\n\ndef helper():\n    raise ValueError\n",
        encoding="utf-8")
    agent = CodeAgent(FakeTrunk({}, str(tmp_path)), str(tmp_path))
    output = 'File "core/m.py", line 6, in helper\nE   assert 0'
    digest = agent._failure_digest(
        {"results": [{"ok": False, "command": "pytest", "output": output}]}, {})
    assert "失败定位" in digest
    assert "helper" in digest


def test_failure_digest_respects_off_switch(tmp_path):
    agent = CodeAgent(FakeTrunk({"code.locate_failures": "off"}, str(tmp_path)),
                      str(tmp_path))
    output = 'File "core/m.py", line 6, in helper'
    digest = agent._failure_digest(
        {"results": [{"ok": False, "command": "pytest", "output": output}]}, {})
    assert "失败定位" not in digest
