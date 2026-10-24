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


def test_ai_panel_round_limit_and_queue_visible(wb):
    """轮次上限可配置 + 任务队列是面板的一等公民。"""
    spin = wb.ai_dock.rounds_spin
    assert spin.minimum() == 1 and spin.maximum() == 15
    assert 1 <= spin.value() <= 15
    assert wb.ai_dock.queue_list is not None
    assert wb.ai_dock.queue_list.toolTip()


def test_editor_toolbar_is_grouped(wb):
    """工具条按文件/运行/AI 分组，关闭按钮靠右，不再是一条长龙。"""
    from PyQt5.QtWidgets import QPushButton
    labels = [b.text() for b in wb.findChildren(QPushButton)]
    for want in ("📄 新建", "💾 保存", "▶ 运行", "🔧 AI 修复", "✕ 关闭"):
        assert any(want in x for x in labels), labels


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


# ---------------- 入口合并：只保留一个「工作台」 ----------------
def test_feature_registry_has_single_workbench():
    from core.feature_registry import FEATURES
    assert "workbench" in FEATURES
    f = FEATURES["workbench"]
    assert "工作台" in f.label
    assert f.action == "open_workbench"


def test_old_feature_ids_removed_from_menu():
    """三个旧入口必须从菜单里消失，只留 workbench。"""
    from core.feature_registry import MORE_MENU_GROUPS
    ids = [i for _g, group in MORE_MENU_GROUPS for i in group]
    for old in ("code_editor", "agent_journey", "code_agent"):
        assert old not in ids, "%s 仍在菜单里" % old
    assert "workbench" in ids


def test_old_feature_ids_still_resolve_as_alias():
    """旧 id 保留为别名，避免历史调用/文档失效。"""
    from core.feature_registry import get_feature
    for old in ("code_editor", "agent_journey", "code_agent"):
        f = get_feature(old)
        assert f is not None, "%s 解析失败" % old
        assert f.label == "工作台"


def test_toolbar_button_is_workbench(app):
    """主界面工具条只保留一个「工作台」按钮。"""
    import os as _os
    _os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from PyQt5.QtWidgets import QPushButton
    from gui.main_window import JarvisWindow
    w = JarvisWindow()
    try:
        w.show()
        app.processEvents()
        assert "工作台" in w.editor_btn.text()
        texts = [b.text() for b in w.findChildren(QPushButton)]
        for old in ("代码编辑器", "Agent 旅程", "AI 代码 Agent"):
            assert not any(old in x for x in texts), "残留旧按钮: %s" % old
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass


# ---------------- 文字不被压扁（全局 padding 回归） ----------------
def test_global_button_padding_leaves_room_for_text(app):
    """回归：全局 QPushButton 的 padding 曾经是 10px。

    工作台工具条按钮高度只有 24~27px，24 - 20(上下padding) - 2(边框)
    = 2px 留给文字，中文被压成一条横线（"文字显示不全"）。
    这里断言 padding 不超过 6px，且最小高度够放一行 13px 中文。
    """
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QPushButton
    from gui.style import STYLE

    app.setStyleSheet(STYLE)
    assert "padding: 10px" not in STYLE, "全局按钮 padding 又变回 10px 了"
    b = QPushButton("▶ 开始")
    b.show()
    app.processEvents()
    fm = QFontMetrics(b.font())
    assert b.height() >= fm.height() + 8, (
        "按钮高度 %d 放不下一行 %dpx 文字" % (b.height(), fm.height()))
    b.close()


def test_workbench_buttons_have_enough_height(app):
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QAbstractButton

    from gui.style import STYLE
    from gui.workbench_dialog import WorkbenchWindow

    app.setStyleSheet(STYLE)

    class T:
        base = BASE
        config = {}

        def __init__(self):
            self.modules = {}

    wb = WorkbenchWindow(T())
    try:
        wb.show()
        app.processEvents()
        tight = []
        for b in wb.findChildren(QAbstractButton):
            if not b.text():
                continue
            fm = QFontMetrics(b.font())
            if b.height() < fm.height() + 4:
                tight.append((b.text()[:16], b.height(), fm.height()))
        assert not tight, "这些按钮高度不足以显示文字: %s" % tight
    finally:
        try:
            wb.close()
        except Exception:  # 静默是故意的
            pass
        QCoreApplication.processEvents()
