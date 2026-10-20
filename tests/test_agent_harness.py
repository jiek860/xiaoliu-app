# -*- coding: utf-8 -*-
"""Agent Harness / 活动注册表 / 统一错误信封测试。"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.agent_harness import (  # noqa: E402
    RunRegistry, get_run_registry, normalize_error, reset_run_registry,
    TERMINAL_STATUSES,
)

from PyQt5.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("text,code", [
    ("模型未配置，请去设置", "MODEL_NOT_CONFIGURED"),
    ("权限被拒绝：未授权", "PERMISSION_DENIED"),
    ("网络策略拒绝 network denied", "NETWORK_DENIED"),
    ("工具不存在 not found", "TOOL_NOT_FOUND"),
    ("任务超时 timeout", "TASK_TIMEOUT"),
    ("测试失败 AssertionError", "TEST_FAILED"),
    ("文件已被修改 hash 冲突", "FILE_CONFLICT"),
    ("普通失败 failed", "TASK_FAILED"),
])
def test_normalize_error_has_single_next_action(text, code):
    env = normalize_error(text)
    assert env["ok"] is False
    assert env["code"] == code
    assert env["title"]
    assert env["message"]
    assert env["next_action"]["id"]
    assert env["next_action"]["label"]
    assert env["technical_detail"]


def test_run_registry_lifecycle_and_subscriber():
    reg = RunRegistry()
    events = []
    reg.subscribe(lambda run, event: events.append((event, run.get("run_id"))))
    run = reg.start_run("job", "测试活动", run_id="r1", budget={"max_seconds": 60})
    assert reg.active_count() == 1
    reg.update_run("r1", current_step="执行中", progress=0.5)
    reg.finish_run("r1", "completed")
    assert reg.active_count() == 0
    assert reg.get_run("r1")["status"] == "completed"
    assert [e for e, _ in events] == ["started", "updated", "updated"]


def test_registry_upsert_task_has_progress_and_error():
    reg = RunRegistry()
    task = {
        "id": "t1", "goal": "整理资料", "status": "failed",
        "trace_id": "trace_t1", "budget": {"max_seconds": 300},
        "usage": {"tool_calls": 2}, "error": "权限被拒绝",
        "steps": [
            {"id": "s1", "title": "读取", "status": "done"},
            {"id": "s2", "title": "写入", "status": "failed"},
        ],
    }
    run = reg.upsert_task(task, "step_failed", "写入")
    assert run["run_id"] == "task:t1"
    assert run["task_id"] == "t1"
    assert run["progress"] == 0.5
    assert run["error"] == "权限被拒绝"
    assert run["finished_at"] > 0


def test_task_runtime_emits_into_registry():
    from tests.conftest import make_trunk
    reset_run_registry()
    trunk = make_trunk()
    rt = trunk.get_task_runtime()
    task = rt.create("注册表任务")
    run = get_run_registry().get_run("task:" + task["id"])
    assert run is not None
    assert run["title"] == "注册表任务"
    assert run["status"] in ("pending", "planning", "running")


def test_activity_center_dialog_constructs():
    from tests.conftest import make_trunk
    from gui.activity_center_dialog import ActivityCenterDialog
    reset_run_registry()
    trunk = make_trunk()
    trunk.get_task_runtime().create("活动中心测试")
    w = ActivityCenterDialog(trunk)
    try:
        assert w.windowTitle()
        assert w.list.count() >= 1
    finally:
        w.close()

def test_theme_manager_persists_appearance(tmp_path):
    from gui.theme_manager import ThemeManager
    base = str(tmp_path)
    tm = ThemeManager(base)
    assert tm.appearance["theme"] == "system"
    tm.set_options(theme="dark", font_size=16, density="compact")
    tm2 = ThemeManager(base)
    assert tm2.appearance["theme"] == "dark"
    assert tm2.appearance["font_size"] == 16
    assert tm2.appearance["density"] == "compact"
    assert tm2.stylesheet()


def test_window_state_roundtrip(tmp_path):
    from PyQt5.QtWidgets import QWidget
    from gui.window_state import WindowStateManager
    base = str(tmp_path)
    w = QWidget()
    w.resize(1111, 777)
    mgr = WindowStateManager(base)
    mgr.save(w)
    w2 = QWidget()
    mgr2 = WindowStateManager(base)
    assert mgr2.restore(w2) is True
    assert w2.size().width() >= 800
    assert w2.size().height() >= 600
    w.close()
    w2.close()


def test_feedback_state_components_construct():
    from gui.feedback_states import LoadingWidget, EmptyStateWidget, ErrorCardWidget
    loading = LoadingWidget("加载中")
    empty = EmptyStateWidget("暂无内容", "下一步", "开始", lambda: None)
    error = ErrorCardWidget("权限被拒绝")
    try:
        assert loading.label.text() == "加载中"
        assert error.env["code"] == "PERMISSION_DENIED"
    finally:
        for w in (loading, empty, error):
            w.close()
