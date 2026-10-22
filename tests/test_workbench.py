# -*- coding: utf-8 -*-
"""工作台测试：编辑器 + AI 面板同屏（无功能页签）。"""

import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QTabWidget  # noqa: E402


class _FakeTrunk:
    base = BASE
    config = {}

    def __init__(self):
        self.modules = {}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def wb(app):
    from gui.workbench_dialog import WorkbenchWindow
    w = WorkbenchWindow(_FakeTrunk())
    w.show()
    yield w
    w.close()


# ---------------- 结构 ----------------
def test_workbench_builds(wb):
    assert wb.windowTitle()
    assert wb._editor is not None, "编辑器应被嵌入"
    assert wb.ai_dock is not None


def test_no_feature_tabs(wb):
    """核心要求：不存在"编辑器/旅程/Agent"这种功能页签。"""
    tabs = wb.findChildren(QTabWidget)
    assert len(tabs) <= 1, "工作台不应有多个 QTabWidget"
    if tabs:
        names = [tabs[0].tabText(i) for i in range(tabs[0].count())]
        assert not any("旅程" in n or "Agent" in n for n in names), names


def test_ai_panel_below_editor(wb):
    """方案 A：AI 面板在编辑器下方。"""
    assert wb.vertical.count() == 2
    assert wb.vertical.widget(1) is wb.ai_dock


# ---------------- 收起 / 展开 ----------------
def test_toggle_ai(wb):
    """Ctrl+J 收起/展开 AI 面板（不再占用界面按钮）。"""
    start = wb._ai_shown
    wb.toggle_ai()
    assert wb._ai_shown is (not start)
    wb.toggle_ai()
    assert wb._ai_shown is start


def test_no_redundant_buttons_in_workbench(wb):
    """界面按钮必须精简：只保留无法用一句话替代的动作控制。"""
    from PyQt5.QtWidgets import QPushButton
    texts = [b.text() for b in wb.findChildren(QPushButton)]
    # 动作控制必须有（执行中要能立即停手，不能靠打字）
    assert any("开始" in t for t in texts), texts
    assert any("取消" in t for t in texts), texts
    # 这些已改为快捷键/拖动，不应再有按钮
    assert not any("全屏" in t for t in texts), "全屏应改用 F11"
    assert not any("收起" in t for t in texts), "收起应改用 Ctrl+J"


# ---------------- 弹出 / 收回 ----------------
def test_popup_and_dock_back(wb):
    wb.toggle_ai_popup()
    assert wb._ai_popup is not None
    assert "收回" in wb.ai_dock.expand_btn.text()
    wb.toggle_ai_popup()
    assert wb._ai_popup is None
    assert "弹出" in wb.ai_dock.expand_btn.text()
    assert wb.vertical.count() == 2


def test_popup_repeated_toggle(wb):
    for _ in range(3):
        wb.toggle_ai_popup()
    assert wb._ai_popup is not None
    wb.toggle_ai_popup()
    assert wb._ai_popup is None


# ---------------- 文件上下文 ----------------
def test_open_and_list_files(wb):
    wb.open_path(os.path.join(BASE, "run.py"))
    files = wb.editor_open_files()
    assert any(f.endswith("run.py") for f in files), files


def test_set_goal(wb):
    wb.set_goal("给 main 加参数解析")
    assert wb.ai_dock.goal.toPlainText() == "给 main 加参数解析"


# ---------------- AI 面板控件 ----------------
def test_agent_dock_controls(wb):
    dock = wb.ai_dock
    for attr in ("goal", "start_btn", "pause_btn", "cancel_btn", "timeline"):
        assert hasattr(dock, attr), "缺少 %s" % attr
    assert dock.pause_btn.isEnabled() is False
    assert dock.cancel_btn.isEnabled() is False


def test_empty_goal_is_rejected_without_dialog(wb):
    """空目标必须直接拒绝。

    ⚠️ 不能用 QMessageBox 做校验：offscreen 下它会阻塞并让进程崩溃
       （实测退出码 -1073741819）。所以校验逻辑必须与弹窗分离。
    """
    wb.ai_dock.goal.setPlainText("   ")
    assert wb.ai_dock.can_start() is False
    wb.ai_dock.start()                 # 不弹框、不抛异常
    assert "请先描述" in wb.ai_dock.timeline.toPlainText()


def test_non_empty_goal_can_start(wb):
    wb.ai_dock.goal.setPlainText("给 main 加参数")
    assert wb.ai_dock.can_start() is True


# ---------------- 旧入口兼容 ----------------
def test_legacy_entries_point_to_workbench():
    for rel in (os.path.join("gui", "mixins", "agent_launcher_mixin.py"),
                os.path.join("gui", "mixins", "dialog_mixin.py")):
        src = open(os.path.join(BASE, rel), encoding="utf-8").read()
        assert "open_workbench" in src, rel


# ---------------- 覆盖率补充：AgentDock / 快捷键 ----------------
def test_agent_dock_controls_disabled_before_start(wb):
    dock = wb.ai_dock
    assert dock.pause_btn.isEnabled() is False
    assert dock.cancel_btn.isEnabled() is False


def test_toggle_pause_without_orchestrator_is_safe(wb):
    wb.ai_dock.orchestrator = None
    wb.ai_dock.toggle_pause()      # 不应抛异常
    wb.ai_dock.cancel()            # 不应抛异常


def test_agent_event_appends_to_timeline(wb):
    wb.ai_dock.timeline.clear()
    wb.ai_dock._on_event("测试步骤")
    assert "测试步骤" in wb.ai_dock.timeline.toPlainText()
    wb.ai_dock._on_event("步骤", {"step": "来自 dict 的步骤"})
    assert "来自 dict 的步骤" in wb.ai_dock.timeline.toPlainText()


def test_open_files_returns_list(wb):
    files = wb.editor_open_files()
    assert isinstance(files, list)


def test_toggle_fullscreen_does_not_raise(wb):
    wb.toggle_fullscreen()
    wb.toggle_fullscreen()


def test_shortcuts_installed(wb):
    """Ctrl+J / F11 通过 QShortcut 注入，不作为按钮存在。"""
    from PyQt5.QtWidgets import QShortcut
    keys = []
    for sc in wb.findChildren(QShortcut):
        keys.append(sc.key().toString())
    assert any("Ctrl+J" in k for k in keys), keys
    assert any("F11" in k for k in keys), keys


# ---------------- 覆盖率补充：AgentDock 执行路径 ----------------
class _FakeOrch:
    instances = []

    def __init__(self, trunk, root=None, event_cb=None, approval_cb=None,
                 open_files=None):
        self.trunk = trunk
        self.root = root
        self.event_cb = event_cb
        self.approval_cb = approval_cb
        self.open_files = list(open_files or [])
        self.paused = False
        self.cancelled = False
        self.result = {"ok": True}
        _FakeOrch.instances.append(self)

    def run(self, goal, **_kw):
        if self.event_cb:
            self.event_cb("步骤一", {"step": "步骤一"})
        return self.result

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def cancel(self):
        self.cancelled = True


def _install_fake_orch(monkeypatch):
    import core.agent_orchestrator as ao
    _FakeOrch.instances = []
    monkeypatch.setattr(ao, "AgentOrchestrator", _FakeOrch)
    return _FakeOrch


def test_start_runs_orchestrator(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("给 main 加参数")
    wb.ai_dock.start()
    assert fake.instances, "应该创建了 orchestrator"
    text = wb.ai_dock.timeline.toPlainText()
    assert "目标: 给 main 加参数" in text
    assert "步骤一" in text
    assert wb.ai_dock.start_btn.isEnabled() is True


def test_start_reports_failure_result(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    monkeypatch.setattr(_FakeOrch, "run", lambda self, g, **k: {"ok": False, "error": "boom"})
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    assert "未完成" in wb.ai_dock.timeline.toPlainText()


def test_start_handles_exception(wb, monkeypatch):
    _install_fake_orch(monkeypatch)

    def boom(self, goal, **_k):
        raise RuntimeError("炸了")

    monkeypatch.setattr(_FakeOrch, "run", boom)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    assert "错误" in wb.ai_dock.timeline.toPlainText()
    assert wb.ai_dock.start_btn.isEnabled() is True


def test_pause_and_resume_cycle(wb, monkeypatch):
    _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    orch = wb.ai_dock.orchestrator
    wb.ai_dock.toggle_pause()
    assert orch.paused is True
    wb.ai_dock.toggle_pause()
    assert orch.paused is False


def test_cancel_marks_orchestrator(wb, monkeypatch):
    _install_fake_orch(monkeypatch)
    wb.ai_dock.goal.setPlainText("x")
    wb.ai_dock.start()
    orch = wb.ai_dock.orchestrator
    wb.ai_dock.cancel()
    assert orch.cancelled is True


def test_open_with_agent_passes_files(wb, monkeypatch):
    fake = _install_fake_orch(monkeypatch)
    import os as _os
    wb.open_path(_os.path.join(BASE, "run.py"))
    wb.ai_dock.open_with_agent.setChecked(True)
    wb.ai_dock.goal.setPlainText("改一下")
    wb.ai_dock.start()
    assert fake.instances[-1].open_files, "应把打开的文件传给 Agent"


def test_approve_returns_bool(wb):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.join(BASE, "gui"))
    # 审批回调必须返回布尔（失败时 fail-closed 为 False）
    r = wb.ai_dock._approve("code", "diff --git ...")
    assert r in (True, False)
