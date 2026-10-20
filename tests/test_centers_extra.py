# -*- coding: utf-8 -*-
"""任务中心与安全中心：空状态、基础渲染和锁定入口。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.task_center_dialog import TaskCenterDialog  # noqa: E402
from gui.security_center_dialog import SecurityCenterDialog  # noqa: E402
from tests.conftest import make_trunk  # noqa: E402


class _FakeRT:
    def subscribe(self, _cb):
        return None

    def list_tasks(self):
        return []

    def get_task(self, _task_id):
        return None


class _FakeTrunk:
    config = {"security": {"network_mode": "standard"}}

    def get_task_runtime(self):
        return _FakeRT()


def test_task_center_empty_state_and_actions():
    d = TaskCenterDialog(_FakeTrunk())
    try:
        assert "还没有任务" in d.detail.toPlainText()
        assert set(d.action_buttons) >= {
            "开始", "暂停", "恢复", "取消", "重试失败步骤", "刷新"}
    finally:
        d.close()


def test_task_center_handles_task_list(monkeypatch):
    class RT(_FakeRT):
        def list_tasks(self):
            return [{"id": "t1", "status": "running", "goal": "整理资料"}]

        def get_task(self, task_id):
            return {"id": task_id, "status": "running", "goal": "整理资料",
                    "budget": {"max_seconds": 60}, "steps": [
                        {"id": "s1", "status": "running", "title": "检索"}]}

    class T(_FakeTrunk):
        def get_task_runtime(self):
            return RT()

    d = TaskCenterDialog(T())
    try:
        assert d.list.count() == 1
        assert "整理资料" in d.detail.toPlainText()
    finally:
        d.close()


def test_security_center_renders_and_toggles_lock(monkeypatch):
    trunk = make_trunk()
    from core.permission_center import get_permission_center
    pc = get_permission_center(trunk)
    pc.lockdown(False)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    d = SecurityCenterDialog(trunk)
    try:
        assert d.tabs.count() == 3
        assert "网络模式" in d.summary.text()
        d._toggle_lock()
        assert get_permission_center(trunk).locked is True
        d._toggle_lock()
        assert get_permission_center(trunk).locked is False
    finally:
        get_permission_center(trunk).lockdown(False)
        d.close()