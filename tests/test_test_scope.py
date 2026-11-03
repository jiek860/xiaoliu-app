# -*- coding: utf-8 -*-
"""测试范围收窄：只新建独立 Python 文件时，用编译检查代替全量测试。

背景：工作台默认工作区是程序自己的目录，``pytest -q`` 一轮约 5 分钟、
还有 300 秒超时；新建一个独立小脚本根本不需要跑别人的几千条用例，
那些无关失败还会被当成"这次代码写错了"反复回修。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code_command_runner import CodeCommandRunnerMixin  # noqa: E402


class _Agent(CodeCommandRunnerMixin):
    def __init__(self, root, test_commands=None):
        self.root = str(root)
        self.trunk = None
        self.test_commands = list(test_commands or ['"%s" -m pytest -q'
                                                    % sys.executable])
        self.commands = []

    def _check_control(self):
        return None

    def _run_command(self, cmd, timeout=300, sandboxed=False):
        """记录命令但不真跑，避免测试里去执行全量 pytest。"""
        self.commands.append(str(cmd))
        return {"ok": True, "exit_code": 0, "output": "", "command": str(cmd),
                "duration": 0, "timed_out": False, "cancelled": False}


def _write(root, rel, text):
    path = os.path.join(str(root), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_new_python_file_runs_compile_only(tmp_path):
    _write(tmp_path, "hello.py", "print('hi')\n")
    agent = _Agent(tmp_path)
    result = agent.run_tests(changed_files=["hello.py"],
                             created_files=["hello.py"])
    assert result["compile_only"] is True
    assert result["ok"] is True
    assert agent.commands == [], "新建文件不应跑全量 pytest"
    assert result["results"][0]["command"].startswith("py_compile hello.py")


def test_syntax_error_in_new_file_still_fails(tmp_path):
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
    agent = _Agent(tmp_path)
    result = agent.run_tests(changed_files=["bad.py"], created_files=["bad.py"])
    assert result["compile_only"] is True
    assert result["ok"] is False


def test_mixed_edit_and_create_keeps_full_tests(tmp_path):
    """同时也改了已有文件：不能只编译新建的那个，回归风险还在。"""
    _write(tmp_path, "new_one.py", "print('ok')\n")
    _write(tmp_path, "old_one.py", "x = 1\n")
    agent = _Agent(tmp_path)
    result = agent.run_tests(changed_files=["new_one.py", "old_one.py"],
                             created_files=["new_one.py"])
    assert "compile_only" not in result
    assert agent.commands, "改到已有文件时应走全量测试"


def test_non_python_create_keeps_full_tests(tmp_path):
    _write(tmp_path, "notes.txt", "hello\n")
    agent = _Agent(tmp_path)
    result = agent.run_tests(changed_files=["notes.txt"],
                             created_files=["notes.txt"])
    assert "compile_only" not in result
    assert agent.commands


def test_no_created_files_runs_full_tests(tmp_path):
    _write(tmp_path, "m.py", "x = 1\n")
    agent = _Agent(tmp_path)
    result = agent.run_tests(changed_files=["m.py"])
    assert "compile_only" not in result
    assert agent.commands == ['"%s" -m pytest -q' % sys.executable]


def test_compile_scope_caps_file_count(tmp_path):
    for i in range(14):
        _write(tmp_path, "f%02d.py" % i, "x = %d\n" % i)
    agent = _Agent(tmp_path)
    names = ["f%02d.py" % i for i in range(14)]
    only = agent._compile_scope(names)
    assert only["compile_only"] is True
    assert len(only["results"]) == 10
