# -*- coding: utf-8 -*-
"""类型化电脑动作 schema 与 ComputerAgent harness 测试。"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.action_schema import (  # noqa: E402
    ActionError, action_summary, make_action, requires_confirmation,
    validate_action,
)
from core.agent_harness import reset_run_registry  # noqa: E402
from core.computer_agent import ComputerAgent  # noqa: E402


class FakeController:
    def __init__(self, base):
        self.base = base
        self.calls = []
        self._shot = 0

    def list_windows(self):
        return ["记事本", "浏览器"]

    def get_active_window(self):
        return "记事本"

    def screenshot(self, path=None):
        self._shot += 1
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "wb").write(b"png-%d" % self._shot)
        return True, path or ""

    def ui_dump(self, window=None, depth=3):
        return {"ok": True, "结构":
                "ButtonControl  「保存」  @(100,200,80,30)\n"
                "  EditControl  「文件名」  @(20,20,200,30)"}

    def ui_click(self, name, control_type=None, window=None):
        self.calls.append(("click", name, window))
        return True, "clicked " + str(name)

    def type_text(self, text):
        self.calls.append(("type", text))
        return True, "typed"

    def open_app(self, name):
        self.calls.append(("open", name))
        return True, "opened"

    def mouse_click(self, x, y, button="left", clicks=1):
        self.calls.append(("mouse", x, y))
        return True, "mouse clicked"


class FakeTrunk:
    allow_headless_agent = True

    def __init__(self, base):
        self.base = base
        self.modules = {"computer_controller": FakeController(base)}

    def call(self, *a, **k):
        return {"ok": True}


def test_action_schema_validation_and_risk():
    a = make_action("click", target={"name": "保存"})
    assert validate_action(a)["type"] == "click"
    assert "点击" in action_summary(a)
    assert requires_confirmation(make_action("shell", args={"cmd": "git status"}))
    with pytest.raises(ActionError):
        validate_action({"type": "unknown"})
    with pytest.raises(ActionError):
        validate_action({"type": "click", "target": {}, "args": {}})


def test_computer_agent_observe_execute_verify(tmp_path):
    reset_run_registry()
    agent = ComputerAgent(FakeTrunk(str(tmp_path)))
    snap = agent.observe()
    assert "记事本" in snap["window_titles"]
    assert snap["screenshot"]

    click = make_action("click", target={"name": "保存"},
                        verify={"type": "window_title", "expected": "记事本"})
    result = agent.execute(click)
    assert result["ok"] is True
    assert agent.verify(click, result)["ok"] is True


def test_computer_agent_run_actions_success(tmp_path):
    reset_run_registry()
    agent = ComputerAgent(FakeTrunk(str(tmp_path)))
    actions = [
        make_action("click", target={"name": "保存"}),
        make_action("type", args={"text": "hello"}),
        make_action("open_app", args={"name": "记事本"}),
    ]
    r = agent.run_actions(actions, title="测试电脑任务", verify_each=False)
    assert r["ok"] is True
    assert len(r["trace"]) == 3


def test_visual_grounding_finds_control(tmp_path):
    reset_run_registry()
    agent = ComputerAgent(FakeTrunk(str(tmp_path)))
    snap = agent.observe()
    hits = agent.ground("点击保存按钮", snap)
    assert hits
    assert hits[0]["name"] == "保存"


def test_screenshot_diff_verification(tmp_path):
    reset_run_registry()
    agent = ComputerAgent(FakeTrunk(str(tmp_path)))
    before = agent.observe()
    action = make_action("click", target={"name": "保存"},
                         verify={"type": "screenshot_diff"})
    result = agent.execute(action)
    assert agent.verify(action, result, before)["ok"] is True


def test_fuse_uia_ocr_vision_grounding():
    from core.visual_grounding import fuse_grounding
    uia = [{"name": "保存", "type": "ButtonControl",
            "rect": [1, 2, 3, 4], "source": "uia"}]
    hits = fuse_grounding("保存文件", uia_elements=uia,
                          ocr_text="文件名\n保存",
                          vision_text="窗口里有一个保存按钮")
    assert hits
    assert any(h["source"] == "uia" for h in hits)
    assert any(h["source"] == "ocr" for h in hits)


class FakePlannerLLM:
    def chat(self, messages):
        return ('```json\n'
                '{"actions":['
                '{"type":"open_app","args":{"name":"记事本"},'
                '"verify":{"type":"window_title","expected":"记事本"},'
                '"risk":"low","reason":"打开记事本"},'
                '{"type":"click","target":{"name":"保存"},'
                '"verify":{"type":"none"},"risk":"low","reason":"保存"}'
                ']}\n```')


def test_llm_plan_and_run_cross_app_goal(tmp_path):
    reset_run_registry()
    trunk = FakeTrunk(str(tmp_path))
    trunk.modules["llm"] = FakePlannerLLM()
    agent = ComputerAgent(trunk)
    actions = agent.plan_goal("打开记事本并保存")
    assert len(actions) == 2
    assert actions[0]["type"] == "open_app"
    r = agent.run_goal("打开记事本并保存", approval_cb=lambda a: True)
    assert r["ok"] is True, r
    assert len(r["trace"]) == 2


def test_computer_agent_dialog_constructs():
    from tests.conftest import make_trunk
    from gui.computer_agent_dialog import ComputerAgentDialog
    trunk = make_trunk()
    d = ComputerAgentDialog(trunk)
    try:
        assert d.windowTitle() == "电脑 Agent"
        assert d.plan_btn.isEnabled()
        assert not d.run_btn.isEnabled()
    finally:
        d.close()


def test_computer_controller_win_failure_returns_three_tuple(monkeypatch, tmp_path):
    """pywin32 缺失时 _win() 也必须返回三元组，不能被 _all_windows 解包崩。"""
    import builtins
    from modules.installed.computer_controller import ComputerController

    c = ComputerController(FakeTrunk(str(tmp_path)))
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name in ("win32gui", "win32con", "win32api"):
            raise ModuleNotFoundError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    g, con, api = c._win()
    assert isinstance(g, ModuleNotFoundError)
    assert con is None and api is None
    assert c.list_windows() == ["（没有找到可见窗口）"]
