# -*- coding: utf-8 -*-
"""UI 分层、模式切换、设置分级与引导状态测试。"""
import json
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QVBoxLayout, QTabWidget, QPushButton, QWidget,
    QMenu, QLineEdit,
)

_app = QApplication.instance() or QApplication([])

from core.feature_registry import (  # noqa: E402
    ADVANCED, SIMPLE, FEATURES, AVATAR_MENU_IDS, MORE_MENU_GROUPS,
    primary_features, primary_button_budget, feature_ids_for_mode, is_visible,
    get_feature,
)
from gui.ui_mode import (  # noqa: E402
    UIModeManager, get_ui_mode, load_ui_state, set_ui_mode,
)
from gui.guidance import (  # noqa: E402
    GuidanceEngine, next_step, next_step_for_error, classify_error,
)


def test_simple_primary_buttons_at_most_seven():
    ids = [f.id for f in primary_features(SIMPLE)]
    assert len(ids) <= 7
    assert primary_button_budget(SIMPLE) <= 7


def test_module_buttons_have_visible_labels_and_count():
    from core.module_buttons import load_buttons
    buttons = load_buttons(BASE)
    assert buttons, "manifest 里有按钮，但 load_buttons 没返回"
    assert all(str(b.get("label") or "").strip() for b in buttons)
    src = open(os.path.join(BASE, "gui", "build_ui.py"),
               encoding="utf-8").read()
    assert "模块（%d）" in src
    assert '"暂无模块按钮"' in src


def test_entry_buttons_do_not_start_empty():
    src = open(os.path.join(BASE, "gui", "build_ui.py"),
               encoding="utf-8").read()
    assert 'win.avatar_btn = QPushButton("")' not in src
    assert '_small_button("", "清空聊天")' not in src
    assert "清空" in src


def test_advanced_keeps_all_original_capabilities():
    simple = set(feature_ids_for_mode(SIMPLE))
    advanced = set(feature_ids_for_mode(ADVANCED))
    assert simple <= advanced
    # 需求里明确点名的能力，高级模式必须仍然在
    for fid in ("module_buttons", "realtime_chat", "model_selector",
                "workbench", "security_center", "plugin_market", "mcp",
                "memory", "logs", "task_center"):
        assert fid in advanced
        assert is_visible(fid, ADVANCED)


def test_avatar_menu_is_limited_to_five_high_frequency_actions():
    # 头像菜单固定为：切换模式 / 检查更新 / 设置 / 登录 / 帮助
    assert set(AVATAR_MENU_IDS) == {"update", "settings", "login", "tutorial"}


def test_more_menu_covers_other_features_without_duplicates():
    more_ids = [fid for _group, ids in MORE_MENU_GROUPS for fid in ids]
    assert len(more_ids) == len(set(more_ids)), "更多菜单内部有重复入口"
    assert not (set(more_ids) & set(AVATAR_MENU_IDS)), \
        "头像和更多菜单重复了入口"
    # 原来的低频能力必须仍在更多的分组里
    for fid in ("task_center", "security_center", "plugin_market", "mcp",
                "model_selector", "workbench", "memory", "logs",
                "command_palette", "onboarding", "feedback"):
        assert fid in more_ids


def test_rendered_menus_have_no_duplicate_actions(monkeypatch):
    from gui.mixins.ui_mode_mixin import UIModeMixin

    class FakeWindow(QWidget, UIModeMixin):
        def __init__(self):
            super().__init__()

            class Account:
                def current_username(self):
                    return "tester"

            self.account = Account()
            self.avatar_btn = QPushButton("avatar", self)
            self.more_btn = QPushButton("more", self)
            self.ui_mode_value = SIMPLE
            self._toggle_ui_mode = lambda: None
            for _group, ids in MORE_MENU_GROUPS:
                for fid in ids:
                    feature = get_feature(fid)
                    if feature and not hasattr(self, feature.action):
                        setattr(self, feature.action, lambda: None)

        def update_dialog(self):
            pass

        def set_dialog(self):
            pass

        def show_login(self):
            pass

        def show_tutorial(self):
            pass

    fake = FakeWindow()
    menus = []
    monkeypatch.setattr(
        QMenu, "exec_",
        lambda self, *a, **k: (menus.append(self), 0)[1])
    try:
        fake._show_avatar_menu()
        fake._show_more_menu()
    finally:
        fake.close()

    avatar_texts = [a.text().strip() for a in menus[0].actions()
                    if not a.isSeparator() and a.isEnabled()]
    assert len(avatar_texts) == 5
    assert any("切换模式" in t for t in avatar_texts)
    for needle in ("检查更新", "设置", "登录 / 切换账号", "帮助"):
        assert any(needle in t for t in avatar_texts)

    more_texts = [a.text().strip() for a in menus[1].actions()
                  if not a.isSeparator() and a.isEnabled()]
    assert len(more_texts) == len(set(more_texts)), "更多菜单渲染出重复按钮"
    assert not (set(more_texts) & set(avatar_texts)), "两个菜单渲染出重复按钮"
    for needle in ("任务中心", "安全中心", "插件市场", "MCP",
                   "命令面板", "意见反馈"):
        assert any(needle in t for t in more_texts)


def test_ui_mode_roundtrip_and_default(tmp_path):
    base = str(tmp_path)
    assert get_ui_mode(base) == SIMPLE
    m = UIModeManager(base)
    assert m.is_simple()
    assert m.toggle() == ADVANCED
    assert get_ui_mode(base) == ADVANCED
    state = load_ui_state(base)
    assert state["ui_mode"] == ADVANCED
    assert state["ui_mode_ever_switched"] is True
    assert state["show_advanced_entries"] is True
    assert m.toggle() == SIMPLE
    assert get_ui_mode(base) == SIMPLE


def test_apply_mode_toggles_visibility():
    from gui.build_ui import apply_ui_mode

    class FakeWindow:
        pass

    w = FakeWindow()
    # 简单模式首屏入口
    for attr in ("new_chat_btn", "nav_list", "session_list", "plus_btn",
                 "mode_combo", "voice_btn", "send_btn"):
        setattr(w, attr, QPushButton("x"))
    # 高级入口
    for attr in ("sidebar_advanced_box", "sidebar_bottom_advanced",
                 "realtime_btn", "model_btn", "editor_btn"):
        setattr(w, attr, QWidget())
    w.more_btn = QPushButton("more")
    w.ui_mode_label = None
    w.brand_label = None
    w.avatar_btn = None
    w.chat = None
    w.model_status_label = None
    apply_ui_mode(w, SIMPLE)
    for attr in ("sidebar_advanced_box", "sidebar_bottom_advanced",
                 "realtime_btn", "model_btn", "editor_btn"):
        assert getattr(w, attr).isHidden(), "%s 在简单模式不该显示" % attr
    for attr in ("new_chat_btn", "nav_list", "plus_btn", "voice_btn",
                 "send_btn"):
        assert not getattr(w, attr).isHidden()
    assert w.more_btn.isHidden(), "简单模式不需要显示更多按钮"
    apply_ui_mode(w, ADVANCED)
    for attr in ("realtime_btn", "model_btn", "editor_btn"):
        assert not getattr(w, attr).isHidden(), "%s 在高级模式应恢复" % attr


def test_settings_simple_has_three_tabs(tmp_path, monkeypatch):
    from gui.settings_dialog import show_settings_dialog
    from gui.ui_mode import set_ui_mode
    from tests.conftest import make_trunk

    # 固定到简单模式，避免本机 data/config.json 里的模式影响测试
    set_ui_mode(str(tmp_path), SIMPLE)

    # 不要真的连 Ollama
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    trunk = make_trunk()
    made = []

    def dlg(title="", width=0, height=0):
        d = QDialog()
        d.setWindowTitle(title or "设置")
        QVBoxLayout(d)
        made.append(d)
        return d, d.layout()

    saved = QDialog.exec_
    QDialog.exec_ = lambda self: 0
    try:
        show_settings_dialog(
            None, dlg, trunk, str(tmp_path), "小6", None, None, None,
            None, None,
            {"知识库": lambda: None, "检查更新": lambda: None,
             "新手教程": lambda: None, "安全中心": lambda: None,
             "意见反馈": lambda: None, "首次设置向导": lambda: None})
    finally:
        QDialog.exec_ = saved
    tabs = made[0].findChildren(QTabWidget)[0]
    assert tabs.count() == 3
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        " 开始", " 使用", " 帮助"]
    search = made[0].findChild(QLineEdit, None)
    # 找到设置搜索框并搜索主题，应切到使用页
    boxes = [x for x in made[0].findChildren(QLineEdit)
             if "搜索" in (x.placeholderText() or "")]
    assert boxes, "设置窗口缺少搜索框"
    boxes[0].setText("主题")
    assert tabs.currentIndex() == 1


def test_guidance_state_persists_and_has_single_next_action(tmp_path):
    g = GuidanceEngine(str(tmp_path))
    assert not g.is_done("first_chat")
    first = g.current()
    assert first["event"] == "first_chat"
    assert first["action"] == "focus_input"
    g.mark_done("first_chat")
    assert g.is_done("first_chat")
    assert g.current()["event"] == "first_task"
    g2 = GuidanceEngine(str(tmp_path))
    assert g2.is_done("first_chat")


@pytest.mark.parametrize("error,event,action", [
    ("权限被拒绝：当前操作未授权", "permission_denied", "open_security_center"),
    ("任务失败：工具不存在", "tool_missing", "open_plugin_market"),
    ("网络策略拒绝：network denied", "network_denied",
     "open_security_network_events"),
    ("任务超时 timeout", "task_timeout", "increase_task_budget"),
    ("未知错误 failed", "task_failed", "retry_failed_step"),
])
def test_failure_guidance_has_unique_next_step(error, event, action):
    item = next_step_for_error(error)
    assert item["event"] == event
    assert item["action"] == action
    assert item["action_label"]


def test_model_not_configured_guidance_points_to_settings():
    item = next_step("model_not_configured")
    assert item["action"] == "open_model_settings"
    assert "模型" in item["title"]

def test_settings_advanced_exposes_tools_extensions_records_developer(
        tmp_path, monkeypatch):
    from gui.settings_dialog import show_settings_dialog
    from gui.ui_mode import set_ui_mode
    from tests.conftest import make_trunk

    monkeypatch.setattr("urllib.request.urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    set_ui_mode(str(tmp_path), ADVANCED)
    trunk = make_trunk()
    made = []

    def dlg(title="", width=0, height=0):
        d = QDialog()
        d.setWindowTitle(title or "设置")
        QVBoxLayout(d)
        made.append(d)
        return d, d.layout()

    saved = QDialog.exec_
    QDialog.exec_ = lambda self: 0
    try:
        show_settings_dialog(
            None, dlg, trunk, str(tmp_path), "小6", None, None, None,
            None, None, {})
    finally:
        QDialog.exec_ = saved
    tabs = made[0].findChildren(QTabWidget)[0]
    labels = [tabs.tabText(i) for i in range(tabs.count())]
    assert len(labels) >= 7
    for name in ("工具", "扩展", "记录", "系统", "开发者"):
        assert any(name in x for x in labels), "高级模式缺少 %s 分组" % name