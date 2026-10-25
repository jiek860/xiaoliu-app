# -*- coding: utf-8 -*-
"""Agent 可控闭环回归测试：路由、权限验证、动态重规划、patch 全操作、回滚。"""
import json
import os
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.action_schema import make_action, validate_action  # noqa: E402
from core.agent_router import route_goal  # noqa: E402
from core.patch_engine import (  # noqa: E402
    apply_patch, rollback, validate_patch,
)
from core.visual_grounding import (  # noqa: E402
    fuse_grounding, parse_ocr_text, parse_uia_lines,
)


def test_action_schema_structured_target_and_verify_types():
    a = make_action("click", target={
        "element_id": "uia_123", "rect": [10, 20, 100, 30],
        "confidence": 0.9})
    assert validate_action(a)["target"]["element_id"] == "uia_123"
    for vtype in ("text_changed", "element_value", "url_contains",
                  "file_contains", "screenshot_diff"):
        v = make_action("type", args={"text": "x"},
                        verify={"type": vtype, "expected": "x"})
        assert validate_action(v)["verify"]["type"] == vtype
    b = make_action("browser_click", args={"selector": "#submit"})
    assert validate_action(b)["type"] == "browser_click"


def test_visual_grounding_returns_element_ids_and_ocr_coords():
    uia = parse_uia_lines(
        "ButtonControl  「保存」  @(100,200,80,30)\n"
        "EditControl  「文件名」  = 「report」  @(20,20,200,30)")
    assert uia and uia[0]["element_id"].startswith("uia_")
    assert uia[1]["value"] == "report"
    ocr = parse_ocr_text("登录按钮 @(300,400,100,40)")
    assert ocr and ocr[0]["rect"] == [300, 400, 100, 40]
    hits = fuse_grounding("保存 登录", uia, ocr_text="登录按钮 @(300,400,100,40)")
    assert hits
    assert all(h.get("element_id") for h in hits)


def test_patch_create_delete_rename_and_rollback(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "old.py").write_text("value = 1\n", encoding="utf-8")
    patch = {
        "goal": "新增、重命名、删除",
        "files": [
            {"op": "create", "path": "new.py", "content": "print('new')\n"},
            {"op": "rename", "path": "old.py", "new_path": "renamed.py"},
            {"op": "update", "path": "renamed.py", "hunks": [
                {"old": "value = 1", "new": "value = 2"}]},
        ],
    }
    validate_patch(str(root), patch)
    r = apply_patch(str(root), patch)
    assert (root / "new.py").read_text(encoding="utf-8") == "print('new')\n"
    assert not (root / "old.py").exists()
    assert "value = 2" in (root / "renamed.py").read_text(encoding="utf-8")
    rb = rollback(r["backup_manifest"])
    assert rb["ok"]
    assert not (root / "new.py").exists()
    assert (root / "old.py").exists()
    assert not (root / "renamed.py").exists()

    # 删除也应可恢复
    p2 = {"files": [{"op": "delete", "path": "old.py"}]}
    r2 = apply_patch(str(root), p2)
    assert not (root / "old.py").exists()
    rollback(r2["backup_manifest"])
    assert (root / "old.py").exists()


class _VerifyController:
    def ui_find(self, **kwargs):
        return {"ok": False, "错误": "not found"}

    def list_windows(self):
        return ["记事本"]

    def get_active_window(self):
        return "记事本"

    def screenshot(self, path=None):
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")
        return True, path or ""

    def ui_dump(self, window=None, depth=3):
        return {"ok": True, "结构": "EditControl  「输入框」  = 「old」  @(1,2,100,20)"}


class _FakeTrunk:
    allow_headless_agent = True

    def __init__(self, base):
        self.base = base
        self.modules = {"computer_controller": _VerifyController()}


def test_control_visible_failed_dict_is_not_success(tmp_path):
    from core.computer_agent import ComputerAgent
    agent = ComputerAgent(_FakeTrunk(str(tmp_path)))
    act = make_action("click", target={"name": "不存在"},
                      verify={"type": "control_visible", "name": "不存在"})
    out = agent.verify(act, {"ok": True})
    assert out["ok"] is False


class _ReplanController:
    def __init__(self):
        self.calls = []

    def list_windows(self):
        return ["桌面"]

    def get_active_window(self):
        return "桌面"

    def screenshot(self, path=None):
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"png")
        return True, path or ""

    def ui_dump(self, window=None, depth=3):
        return {"ok": True, "结构": "ButtonControl  「保存」  @(10,10,50,20)"}

    def ui_click(self, name, control_type=None, window=None):
        self.calls.append(name)
        if name == "不存在":
            return {"ok": False, "错误": "not found"}
        return {"ok": True, "结果": "clicked"}

    def open_app(self, app):
        self.calls.append("open:" + str(app))
        return True, "opened"

    def mouse_click(self, x, y, button="left", clicks=1):
        self.calls.append("mouse")
        return True, "clicked"


class _SequenceLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.i = 0

    def chat(self, messages):
        r = self.replies[min(self.i, len(self.replies) - 1)]
        self.i += 1
        return r


def test_computer_agent_dynamic_replans_after_failure(tmp_path):
    from core.computer_agent import ComputerAgent
    controller = _ReplanController()
    trunk = _FakeTrunk(str(tmp_path))
    trunk.modules["computer_controller"] = controller
    trunk.modules["llm"] = _SequenceLLM([
        json.dumps({"done": False, "thought": "先试错误按钮",
                    "action": {"type": "click", "target": {"name": "不存在"},
                               "verify": {"type": "none"}, "risk": "low"}}),
        json.dumps({"done": False, "thought": "换正确方法",
                    "action": {"type": "open_app", "args": {"name": "记事本"},
                               "verify": {"type": "window_title",
                                          "expected": "桌面"}, "risk": "low"}}),
        json.dumps({"done": True, "message": "完成"}),
    ])
    agent = ComputerAgent(trunk, max_steps=5)
    r = agent.run_goal_dynamic("打开记事本", approval_cb=lambda a: True)
    assert r["ok"] is True, r
    assert any("open:记事本" == c for c in controller.calls)
    assert len(r["trace"]) >= 1


def test_router_distinguishes_code_and_computer():
    assert route_goal("修复 tests/test_x.py 的 pytest 报错")["kind"] == "code"
    assert route_goal("打开浏览器搜索天气并截图")["kind"] == "computer"
    assert route_goal("你好，解释一下这个概念")["kind"] == "chat"


class _ToolPatchLLM:
    def __init__(self, root):
        self.root = root
        self.i = 0

    def chat(self, messages):
        self.i += 1
        if self.i == 1:
            return '{"tool":"read_file","args":{"path":"m.py","start":1,"limit":20}}'
        return json.dumps({
            "goal": "把值改成 2",
            "files": [{"path": "m.py", "hunks": [
                {"old": "value = 1", "new": "value = 2", "reason": "测试"}]}],
        })


def test_code_agent_explore_tool_then_patch(tmp_path):
    from core.code_agent import CodeAgent
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    trunk = _FakeTrunk(str(root))
    trunk.modules = {"llm": _ToolPatchLLM(str(root))}
    agent = CodeAgent(trunk, str(root))
    patch = agent.propose_patch("修改 value")
    assert patch["files"][0]["path"] == "m.py"
    assert agent.can_tool_read if hasattr(agent, "can_tool_read") else True


def test_code_agent_default_test_command_does_not_nameerror(tmp_path):
    from core.code_agent import CodeAgent
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    trunk = _FakeTrunk(str(root))
    trunk.modules = {}
    agent = CodeAgent(trunk, str(root))
    cmds = agent.detect_test_commands()
    assert cmds and "pytest" in cmds[0]
    r = agent.run_tests()
    assert r["ok"] is True, r


def test_agent_journey_dialog_constructs():
    from gui.agent_journey_dialog import AgentJourneyDialog
    d = AgentJourneyDialog(_FakeTrunk(tempfile.mkdtemp()))
    try:
        assert d.windowTitle() == "Agent 旅程"
        assert d.route_combo.count() >= 4
    finally:
        d.close()


def test_agent_journey_plan_event_and_approval(monkeypatch):
    """计划事件要展示到时间线；plan 审批复用同一个确认弹窗。"""
    from PyQt5.QtWidgets import QMessageBox
    from gui.agent_journey_dialog import AgentJourneyDialog

    d = AgentJourneyDialog(_FakeTrunk(tempfile.mkdtemp()))
    try:
        class _Worker:
            result = None

            def resolve_approval(self, value):
                self.result = value

            def isRunning(self):
                return False

        d.worker = _Worker()
        d._on_event("plan", {"step": "执行计划已生成", "plan": {
            "summary": "重构计算",
            "steps": [{"title": "改文件", "files": ["a.py"], "risk": "low"}],
        }})
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.Yes))
        d._on_approval("plan", {"summary": "重构计算"})
        assert d.worker.result is True
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.No))
        d._on_approval("plan", None)
        assert d.worker.result is False
    finally:
        d.close()


def test_diff_preview_only_does_not_modify_file(tmp_path):
    from gui.diff_dialog import DiffReviewDialog
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    from core.patch_engine import file_patch
    patch = file_patch("a.txt", "old", "new")
    d = DiffReviewDialog(str(root), patch, apply_on_accept=False)
    try:
        d._apply()
        assert d.accepted is True
        assert d.selected_files == ["a.txt"]
        assert (root / "a.txt").read_text(encoding="utf-8") == "old\n"
    finally:
        d.close()


def test_agent_permission_supports_once_session_and_deny(tmp_path):
    from core.agent_permissions import authorize_agent_action

    class GateTrunk:
        def __init__(self):
            self.base = str(tmp_path)
            self.confirm_cb = lambda action, detail: True
            self.confirm_scope_cb = lambda action, detail: "session"

        def confirm(self, action, detail):
            return True

    action = {"type": "write_file", "risk": "high",
              "args": {"path": str(tmp_path / "a.txt")}}
    trunk = GateTrunk()
    r1 = authorize_agent_action(trunk, "computer_agent", action)
    assert r1["allow"] is True
    # 第二次命中 session 规则，不再要求确认
    calls = {"n": 0}

    def _scope(action, detail):
        calls["n"] += 1
        return "deny"

    trunk.confirm_scope_cb = _scope
    r2 = authorize_agent_action(
        trunk, "computer_agent",
        {"type": "write_file", "risk": "high",
         "args": {"path": str(tmp_path.parent / "outside.txt")}})
    assert r2["allow"] is False
    assert calls["n"] == 1
