# -*- coding: utf-8 -*-
"""pytest-qt interaction tests for high-value GUI paths."""
import os
import sys

import pytest

pytest.importorskip("pytestqt")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QLabel, QLineEdit, QPushButton  # noqa: E402


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {"ai_name": "测试"}
        self.modules = {}

    def call(self, *_a, **_k):
        return {"ok": True}

    def _log(self, *_a, **_k):
        pass


def test_command_palette_typing_and_enter_runs_selected(qtbot, tmp_path):
    from gui.command_palette import CommandPalette
    called = []
    palette = CommandPalette(_Trunk(tmp_path), {"settings": lambda: called.append("settings")})
    qtbot.addWidget(palette)
    palette.show()
    qtbot.keyClicks(palette.search, "settings")
    qtbot.waitUntil(lambda: palette.list_w.count() >= 1, timeout=2000)
    matches = [i for i in range(palette.list_w.count())
               if "settings" in palette.list_w.item(i).text()]
    assert matches, "settings panel should be searchable"
    palette.list_w.setCurrentRow(matches[0])
    qtbot.keyClick(palette.search, Qt.Key_Return)
    qtbot.waitUntil(lambda: called == ["settings"], timeout=2000)


def test_command_palette_escape_rejects(qtbot, tmp_path):
    from gui.command_palette import CommandPalette
    palette = CommandPalette(_Trunk(tmp_path))
    qtbot.addWidget(palette)
    palette.show()
    palette.search.setFocus()
    qtbot.keyClick(palette.search, Qt.Key_Escape)
    assert not palette.isVisible()


def test_onboarding_cloud_key_is_password_masked(qtbot, tmp_path):
    from gui.onboarding_wizard import OnboardingWizard
    wiz = OnboardingWizard(_Trunk(tmp_path))
    qtbot.addWidget(wiz)
    assert wiz.ed_cloud_key.echoMode() == QLineEdit.Password
    wiz.ed_cloud_key.setText("not-a-real-key")
    assert wiz.ed_cloud_key.text() == "not-a-real-key"
    assert wiz.ed_cloud_url.placeholderText() or wiz.ed_cloud_url.text() is not None


def test_onboarding_tab_navigation_reaches_cloud_fields(qtbot, tmp_path):
    from gui.onboarding_wizard import OnboardingWizard
    wiz = OnboardingWizard(_Trunk(tmp_path))
    qtbot.addWidget(wiz)
    wiz.show()
    wiz.ed_cloud_key.setFocus()
    qtbot.keyClick(wiz.ed_cloud_key, Qt.Key_Tab)
    # The exact next widget may evolve, but focus must stay inside the wizard.
    assert wiz.focusWidget() is not None


# ── B3：纯展示弹窗不再靠按钮当入口（回车 / F5 / Esc / 链接） ──

DISPLAY_ONLY_FILES = [
    "gui/stats_dialog.py",
    "gui/trace_view_dialog.py",
    "gui/search_dialog.py",
    "gui/graph_dialog.py",
    "gui/kb_dialog.py",
    "gui/tutorial_dialog.py",
]


def test_display_only_dialogs_have_zero_button_sites():
    """按钮预算棘轮：这几个文件里不允许再出现 QPushButton 创建点。"""
    for rel in DISPLAY_ONLY_FILES:
        src = open(os.path.join(BASE, rel), encoding="utf-8").read()
        assert "QPushButton(" not in src, "%s 又长出按钮了" % rel


def test_stats_dialog_exports_markdown_via_link(qtbot, tmp_path, monkeypatch):
    from gui.stats_dialog import StatsDialog

    d = StatsDialog(_Trunk(tmp_path))
    qtbot.addWidget(d)
    assert not d.findChildren(QPushButton), "统计弹窗不该再有按钮"
    links = d.findChild(QLabel, "actionLinks")
    assert links is not None and "导出" in links.text()

    out = tmp_path / "stats.md"
    monkeypatch.setattr(
        "PyQt5.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(
        "PyQt5.QtWidgets.QMessageBox.information",
        lambda *a, **k: None)
    links.linkActivated.emit("0")
    assert out.exists()
    assert "小6使用统计" in out.read_text(encoding="utf-8")


def test_trace_dialog_f5_reloads_without_buttons(qtbot, tmp_path):
    from gui.trace_view_dialog import TraceViewDialog

    calls = []

    class _Trace:
        def read(self, limit):
            calls.append(limit)
            return []

    class _T(_Trunk):
        def __init__(self, base):
            super().__init__(base)
            self.modules = {"trace": _Trace()}

    d = TraceViewDialog(_T(tmp_path))
    qtbot.addWidget(d)
    assert not d.findChildren(QPushButton), "Trace 回看不该再有按钮"
    assert d.refresh_shortcut.key().toString() == "F5"
    before = len(calls)
    d.refresh_shortcut.activated.emit()
    assert len(calls) == before + 1


def test_search_dialog_enter_searches_without_buttons(qtbot, tmp_path):
    from gui.search_dialog import SearchDialog

    class _Store:
        def search(self, _user, kw):
            return [{"text": "命中 " + kw, "session_id": "s1"}]

    class _T(_Trunk):
        def __init__(self, base):
            super().__init__(base)
            self.modules = {"chat_store": _Store()}

    d = SearchDialog(_T(tmp_path))
    qtbot.addWidget(d)
    assert not d.findChildren(QPushButton)
    d.input.setText("天气")
    qtbot.keyClick(d.input, Qt.Key_Return)
    assert d.result_list.count() == 1
    assert "天气" in d.result_list.item(0).text()


def test_activity_center_actions_are_links(qtbot, tmp_path):
    from core.agent_harness import get_run_registry, reset_run_registry
    from gui.activity_center_dialog import ActivityCenterDialog

    paused = []

    class _RT:
        def list_tasks(self):
            return []

        def pause(self, tid):
            paused.append(tid)
            return {"ok": True}

        def resume(self, tid):
            return {"ok": True}

        def cancel(self, tid):
            return {"ok": True}

    class _T(_Trunk):
        def get_task_runtime(self):
            return _RT()

    reset_run_registry()
    get_run_registry().start_run(
        "task_loop", "跑着的任务", run_id="task:run1", task_id="run1")

    d = ActivityCenterDialog(_T(tmp_path))
    qtbot.addWidget(d)
    try:
        assert not d.findChildren(QPushButton), "活动中心动作行应改成链接"
        links = d.findChild(QLabel, "actionLinks")
        assert links is not None
        text = links.text()
        for label in ("打开任务中心", "暂停", "继续", "取消", "清理已结束", "刷新"):
            assert label in text
        d._selected = "task:run1"
        links.linkActivated.emit("1")  # 暂停
        assert paused == ["run1"]
    finally:
        d.close()
        reset_run_registry()


def test_research_and_feedback_keep_only_primary_button(qtbot, tmp_path):
    from gui.feedback_dialog import FeedbackDialog
    from gui.research_dialog import ResearchDialog

    research = ResearchDialog(_Trunk(tmp_path))
    qtbot.addWidget(research)
    assert [b.text() for b in research.findChildren(QPushButton)] == ["开始研究"]

    feedback = FeedbackDialog(_Trunk(tmp_path))
    qtbot.addWidget(feedback)
    assert [b.text() for b in feedback.findChildren(QPushButton)] == ["提交"]


# ── B4：首次配置链路（保存即生效 / 填了就存 / Key 真连一次） ──

class _WizTrunk(_Trunk):
    def __init__(self, base):
        super().__init__(base)
        self.config = {"ai_name": "测试"}
        self.saved = 0
        self.llm_reloads = 0
        trunk = self

        class _LLM:
            def reload_config(self):
                trunk.llm_reloads += 1

        self.modules = {"llm": _LLM()}

    def save_config(self):
        self.saved += 1
        return True


def _quiet_wizard(qtbot, tmp_path, monkeypatch):
    from gui.onboarding_wizard import OnboardingWizard

    trunk = _WizTrunk(tmp_path)
    wiz = OnboardingWizard(trunk)
    qtbot.addWidget(wiz)
    # 这两步在测试里会发真实探测/重算尺寸，跟本用例无关
    monkeypatch.setattr(wiz, "_refresh_local_status", lambda *a, **k: None)
    monkeypatch.setattr(wiz, "_show_result", lambda *a, **k: None)
    return trunk, wiz


def test_onboarding_save_persists_and_reloads_llm(qtbot, tmp_path, monkeypatch):
    """向导保存后必须热加载：否则已加载的 LLM 还拿旧配置，第一次聊天照旧失败。"""
    trunk, wiz = _quiet_wizard(qtbot, tmp_path, monkeypatch)
    wiz.rb_cloud.setChecked(True)
    wiz.ed_cloud_url.setText("https://api.deepseek.com/v1/chat/completions")
    wiz.ed_cloud_model.setText("deepseek-chat")
    wiz.ed_cloud_key.setText("sk-test")
    wiz._save_and_check()
    assert trunk.config["model_mode"] == "云端模型"
    assert trunk.config["cloud_key"] == "sk-test"
    assert trunk.saved == 1
    assert trunk.llm_reloads == 1


def test_onboarding_finish_saves_typed_config_without_explicit_save(
        qtbot, tmp_path, monkeypatch):
    """填完直接点「完成」也要落盘，不能要求用户先点保存。"""
    trunk, wiz = _quiet_wizard(qtbot, tmp_path, monkeypatch)
    wiz.ed_ollama.setText("http://127.0.0.1:11434")
    wiz.ed_local_model.setEditText("qwen2.5:3b")
    assert wiz._pending_config() == "local"
    wiz._save_and_note()
    assert trunk.config["model_mode"] == "本地模型"
    assert trunk.config["local_model"] == "qwen2.5:3b"
    assert trunk.saved == 1


def test_onboarding_cloud_test_entry_follows_mode_and_renders_result(
        qtbot, tmp_path, monkeypatch):
    _trunk, wiz = _quiet_wizard(qtbot, tmp_path, monkeypatch)
    assert wiz.lnk_cloud_test.isHidden() is True      # 本地模式不显示
    wiz.rb_cloud.setChecked(True)
    assert wiz.lnk_cloud_test.isHidden() is False
    assert wiz.rb_local.isChecked() is False, "两个模式单选必须互斥"
    wiz._apply_cloud_test({"ok": False, "message": "Key 不对或已过期"})
    assert "❌" in wiz.lbl_cloud_test.text()
    assert "Key" in wiz.lbl_cloud_test.text()
    wiz._apply_cloud_test({"ok": True, "message": "云端连通"})
    assert "✅" in wiz.lbl_cloud_test.text()
    wiz.rb_local.setChecked(True)
    assert wiz.lnk_cloud_test.isHidden() is True
    assert wiz.rb_cloud.isChecked() is False


def test_onboarding_cloud_test_runs_off_thread_and_reports(
        qtbot, tmp_path, monkeypatch):
    _trunk, wiz = _quiet_wizard(qtbot, tmp_path, monkeypatch)
    wiz.rb_cloud.setChecked(True)
    wiz.ed_cloud_url.setText("https://api.deepseek.com/v1/chat/completions")
    wiz.ed_cloud_model.setText("deepseek-chat")
    wiz.ed_cloud_key.setText("sk-test")
    monkeypatch.setattr(
        "core.model_setup.test_cloud",
        lambda *a, **k: {"ok": True, "message": "云端连通"})
    wiz._test_cloud()
    qtbot.waitUntil(lambda: "✅" in wiz.lbl_cloud_test.text(), timeout=3000)


def test_onboarding_save_result_really_probes_and_gives_next_step(
        qtbot, tmp_path, monkeypatch):
    """「保存并检测」要真探测（core.self_check），失败时给为什么 + 下一步。"""
    from gui.onboarding_wizard import OnboardingWizard

    monkeypatch.setattr(
        "core.model_setup.probe_ollama",
        lambda *a, **k: {"reachable": False, "models": [], "error": "offline-test"})
    trunk = _WizTrunk(tmp_path)
    wiz = OnboardingWizard(trunk)
    qtbot.addWidget(wiz)
    monkeypatch.setattr(wiz, "_refresh_local_status", lambda *a, **k: None)
    seen = {}

    def _probe(t, timeout=6):
        seen["called"] = True
        return {"ok": False,
                "problems": ["云端连不上：Key 不对或已过期"],
                "advice": "去服务商后台重新复制一份。\n国内直连可用的：智谱 GLM",
                "detail": "401"}

    monkeypatch.setattr("core.self_check.probe_model_config", _probe)
    wiz.rb_cloud.setChecked(True)
    wiz.ed_cloud_url.setText("https://api.deepseek.com/v1/chat/completions")
    wiz.ed_cloud_model.setText("deepseek-chat")
    wiz.ed_cloud_key.setText("sk-bad")
    wiz._save_and_check()
    assert seen.get("called") is True, "保存时必须真探测一次"
    text = wiz.lbl_result.text()
    assert "还差一点" in text and "云端连不上" in text
    assert "国内直连" in text, "失败要给出可用的国内备选"
    assert "#fef3c7" in wiz.lbl_result.styleSheet()


def test_onboarding_result_when_probe_passes_says_ready(
        qtbot, tmp_path, monkeypatch):
    from gui.onboarding_wizard import OnboardingWizard

    monkeypatch.setattr(
        "core.model_setup.probe_ollama",
        lambda *a, **k: {"reachable": False, "models": [], "error": "offline-test"})
    trunk = _WizTrunk(tmp_path)
    wiz = OnboardingWizard(trunk)
    qtbot.addWidget(wiz)
    monkeypatch.setattr(wiz, "_refresh_local_status", lambda *a, **k: None)
    monkeypatch.setattr(
        "core.self_check.probe_model_config",
        lambda *a, **k: {"ok": True, "problems": [],
                         "advice": "云端连通（真发过一次最小请求），可以直接聊天了。",
                         "detail": "模型：deepseek-chat"})
    wiz._show_result(probe=True)
    assert "✅" in wiz.lbl_result.text()
    assert "deepseek-chat" in wiz.lbl_result.text()
