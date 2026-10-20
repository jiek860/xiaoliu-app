# -*- coding: utf-8 -*-
"""Agent E2E 回归：真实文件、真实 pytest 子进程、动态电脑任务与回滚。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.agent_harness import reset_run_registry  # noqa: E402
from core.code_agent import CodeAgent  # noqa: E402
from core.computer_agent import ComputerAgent  # noqa: E402


class _LLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.i = 0

    def chat(self, messages):
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


class _Trunk:
    allow_headless_agent = True

    def __init__(self, base, llm=None, controller=None):
        self.base = base
        self.modules = {}
        if llm is not None:
            self.modules["llm"] = llm
        if controller is not None:
            self.modules["computer_controller"] = controller


def test_code_agent_e2e_real_pytest_and_rollback(tmp_path):
    reset_run_registry()
    root = tmp_path / "repo"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                  encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    llm = _LLM([json.dumps({
        "goal": "修复加法",
        "files": [{"path": "calc.py", "hunks": [
            {"old": "return a - b", "new": "return a + b",
             "reason": "修复加法"}]}],
    }, ensure_ascii=False)])
    trunk = _Trunk(str(root), llm=llm)
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -m pytest -q' % sys.executable])
    r = agent.run("修复 calc.add 并跑测试", approved_cb=lambda p: True)
    assert r["ok"] is True, r
    assert "return a + b" in (root / "calc.py").read_text(encoding="utf-8")
    assert r["tests"]["ok"] is True
    rb = agent.rollback_all(r["backups"])
    assert rb["ok"] is True
    assert "return a - b" in (root / "calc.py").read_text(encoding="utf-8")


class _DesktopController:
    def __init__(self, base):
        self.base = base
        self.calls = []

    def list_windows(self):
        return ["桌面", "记事本"]

    def get_active_window(self):
        return "记事本"

    def screenshot(self, path=None):
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")
        return True, path or ""

    def ui_dump(self, window=None, depth=3):
        return {"ok": True, "结构":
                "ButtonControl  「保存」  @(10,10,50,20)\n"
                "EditControl  「文件名」  = 「report.txt」  @(20,40,200,20)"}

    def ui_click(self, name, control_type=None, window=None):
        self.calls.append(("click", name))
        return {"ok": True, "结果": "clicked"}

    def type_text(self, text):
        self.calls.append(("type", text))
        return True, "typed"

    def open_app(self, app):
        self.calls.append(("open", app))
        return True, "opened"

    def create_file(self, path, content=""):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.calls.append(("write", path))
        return True, "written"

    def delete_file(self, path):
        if os.path.isfile(path):
            os.remove(path)
            self.calls.append(("delete", path))
        return True, "deleted"

    def hotkey(self, keys):
        return True, "hotkey"

    def press_key(self, key):
        return True, "key"


def test_computer_agent_e2e_dynamic_write_verify_rollback(tmp_path):
    reset_run_registry()
    target = str(tmp_path / "out" / "result.txt")
    ctrl = _DesktopController(str(tmp_path))
    llm = _LLM([
        json.dumps({"done": False, "thought": "写入结果",
                    "action": {"type": "write_file",
                               "args": {"path": target, "content": "hello e2e"},
                               "verify": {"type": "file_exists", "path": target},
                               "risk": "high", "reason": "保存结果"}},
                   ensure_ascii=False),
        json.dumps({"done": True, "message": "已写入并验证"}, ensure_ascii=False),
    ])
    trunk = _Trunk(str(tmp_path), llm=llm, controller=ctrl)
    agent = ComputerAgent(trunk, max_steps=4)
    r = agent.run_goal_dynamic(
        "把结果写入文件", approval_cb=lambda actions: True)
    assert r["ok"] is True, r
    assert open(target, encoding="utf-8").read() == "hello e2e"
    rb = agent.rollback_run(r["run_id"])
    assert rb["ok"] is True
    assert not os.path.exists(target)
