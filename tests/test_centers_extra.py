# -*- coding: utf-8 -*-
"""任务中心与安全中心：空状态、基础渲染和锁定入口。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.task_center_dialog import TaskCenterDialog  # noqa: E402
from gui.mixins.task_entry_mixin import TaskEntryMixin  # noqa: E402
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


# ── B5：任务模式不再在 GUI 线程里拆步，关闭时注销订阅 ──
class _TasksRT(_FakeRT):
    """带任务字典的假运行时：记录 subscribe 注销、拆步与启动。"""

    def __init__(self):
        self.tasks = {}
        self.planned = []
        self.started = []
        self.unsubscribed = []

    def create(self, goal):
        tid = "t9"
        self.tasks[tid] = {"id": tid, "goal": goal, "status": "pending",
                           "steps": [], "budget": {"max_seconds": 60}}
        return dict(self.tasks[tid])

    def _fill_steps(self, task_id):
        t = self.tasks[task_id]
        t["steps"] = [{"id": "step_1", "title": "第一步", "status": "pending",
                       "deps": []}]
        t["status"] = "pending"
        return t

    def plan(self, task_id):
        self.planned.append(task_id)
        return self._fill_steps(task_id)

    def plan_async(self, task_id, on_done=None):
        self.planned.append(task_id)
        self._fill_steps(task_id)
        if on_done:
            on_done(task_id, True)

    def start(self, task_id):
        self.started.append(task_id)
        return {"ok": True}

    def get_task(self, task_id):
        return dict(self.tasks.get(task_id) or {})

    def list_tasks(self):
        return list(self.tasks.values())

    def unsubscribe(self, cb):
        self.unsubscribed.append(cb)
        return True


class _RTTrunk(_FakeTrunk):
    def __init__(self, rt):
        self.rt = rt

    def get_task_runtime(self):
        return self.rt


def test_task_center_plans_in_background_and_keeps_ui_free():
    """新建任务：拆步交给 plan_async（后台线程），按钮立即可用。"""
    rt = _TasksRT()
    d = TaskCenterDialog(_RTTrunk(rt))
    try:
        d.goal.setText("整理资料")
        d._create()
        assert rt.planned == ["t9"], "拆步应该交给后台 plan_async"
        assert d.new_btn.isEnabled() is True
        assert "step_1" in d.detail.toPlainText()
        assert rt.started == [], "只新建不自动运行"
    finally:
        d.done(0)
    assert rt.unsubscribed, "关闭任务中心必须注销运行时订阅"


def test_task_center_auto_plan_starts_given_task():
    """聊天 [任务] 模式：任务已建好，auto_plan 拆完自动开始。"""
    rt = _TasksRT()
    rt.create("聊天转来的任务")
    d = TaskCenterDialog(_RTTrunk(rt), task_id="t9", auto_plan=True)
    try:
        for _ in range(10):
            _app.processEvents()
        assert rt.planned == ["t9"]
        assert rt.started == ["t9"]
    finally:
        d.done(0)


class _CardChat:
    """只记录卡片，不碰真实聊天视图。"""

    def __init__(self):
        self.cards = []

    def append_guidance_card(self, title, message, action, action_label):
        self.cards.append((title, message, action, action_label))


class _TaskEntryHost(QWidget, TaskEntryMixin):
    def __init__(self, rt):
        super().__init__()
        self.trunk = _RTTrunk(rt)
        self.chat = _CardChat()
        self.watched = []

    def _watch_task_result(self, task_id, **_kw):
        self.watched.append(task_id)


def test_chat_task_mode_plans_then_starts_without_blocking():
    rt = _TasksRT()
    task = rt.create("聊天转任务")
    host = _TaskEntryHost(rt)
    try:
        host._plan_task_async(task["id"])
        for _ in range(10):
            _app.processEvents()
        assert rt.planned == [task["id"]]
        assert rt.started == [task["id"]]
        assert host.watched == [task["id"]], "拆完要盯结果"
        assert host.chat.cards == []
    finally:
        host.close()


def test_chat_task_mode_reports_plan_failure_with_next_step():
    class _BadRT(_TasksRT):
        def plan_async(self, task_id, on_done=None):
            if on_done:
                on_done(task_id, False)

    rt = _BadRT()
    task = rt.create("拆不出来")
    host = _TaskEntryHost(rt)
    try:
        host._plan_task_async(task["id"])
        assert rt.started == []
        assert host.chat.cards, "拆步失败要给一张带下一步的卡片"
        title, _msg, action, _label = host.chat.cards[0]
        assert "拆解失败" in title
        assert action.startswith("retry://")
    finally:
        host.close()


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


def _perm_center(tmp_path):
    from core.permission_center import PermissionCenter

    class T:
        base = str(tmp_path)
        config = {}

    return PermissionCenter(T())


def test_permission_revoke_reports_save_failure(tmp_path, monkeypatch):
    """权限文件写不进去时不能说"撤销成功"——重启后权限会复活。"""
    pc = _perm_center(tmp_path)
    pc.rules = [{"id": "r1", "subject": "tool:shell", "scope": "once"}]
    assert pc._save() is True
    monkeypatch.setattr(pc, "_save", lambda: False)
    assert pc.revoke("r1") is False
    # 内存恢复成磁盘上的样子：规则还在，界面不会假装已经删掉
    assert [r["id"] for r in pc.rules] == ["r1"]
    assert any(a.get("result") == "revoke_save_failed"
               for a in pc.audit.list_recent(10))


def test_permission_update_constraints_reports_save_failure(tmp_path, monkeypatch):
    pc = _perm_center(tmp_path)
    pc.rules = [{"id": "r2", "subject": "tool:write", "scope": "always",
                 "constraints": {}}]
    assert pc._save() is True
    monkeypatch.setattr(pc, "_save", lambda: False)
    r = pc.update_constraints("r2", {"file_ext": [".py"]})
    assert r["ok"] is False and "写进" in r["error"]


def test_permission_lockdown_reports_persist_failure(tmp_path, monkeypatch):
    """锁定只在内存生效时要明确提示"重启会失效"。"""
    pc = _perm_center(tmp_path)

    def boom(*_a, **_k):
        raise OSError("只读文件系统")

    monkeypatch.setattr("core.permission_center.os.replace", boom)
    r = pc.lockdown(True)
    assert r["ok"] is False and r["locked"] is True
    assert "重启" in r["error"]


def test_security_center_export_failure_is_reported(monkeypatch):
    trunk = make_trunk()
    from core.permission_center import get_permission_center
    d = SecurityCenterDialog(trunk)
    seen = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.append(a)))
    monkeypatch.setattr(
        "gui.security_center_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: ("audit_export.json", "")))

    def boom(_path, limit=1000):
        raise OSError("只读文件系统")

    monkeypatch.setattr(get_permission_center(trunk).audit,
                        "export_redacted", boom)
    try:
        d._export()
    finally:
        d.close()
    assert seen, "导出失败必须弹提示，不能假装成功"
    assert "只读文件系统" in str(seen[0])