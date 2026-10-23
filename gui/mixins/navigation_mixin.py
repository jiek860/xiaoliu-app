# -*- coding: utf-8 -*-
"""主窗口导航、资源菜单、头像菜单和更多菜单。"""
from __future__ import annotations

import os
import time
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu, QMessageBox, QListWidgetItem
from core.feature_registry import MORE_MENU_GROUPS, SIMPLE, get_feature

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class NavigationMixin:
    def _new_session(self):
        try:
            self.account.new_session()
            self.chat.clear()
            self._refresh_session_list()
            self._refresh_guidance()
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "新建对话", str(e)[:120])

    def _clear_chat(self):
        try:
            self.chat.clear()
            self._refresh_guidance()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _nav_chat(self):
        self._on_composer_mode_changed(0)
        try:
            self.input.setFocus()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _nav_task(self):
        self.start_task()

    def _nav_resources(self):
        self._show_resources_menu()

    def _nav_settings(self):
        self.set_dialog()

    def _on_nav_clicked(self, item):
        key = item.data(Qt.UserRole) if item is not None else ""
        fn = {
            "chat": self._nav_chat,
            "task": self._nav_task,
            "resources": self._nav_resources,
            "settings": self._nav_settings,
        }.get(key)
        if fn:
            fn()
            try:
                self.nav_list.clearSelection()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _on_activity_clicked(self, item):
        """左侧活动栏点击：与菜单入口复用同一批回调，不复制逻辑。"""
        key = item.data(Qt.UserRole) if item is not None else ""
        fn = {
            "chat": self._nav_chat,
            "task": self._nav_task,
            "resources": self._nav_resources,
            "memory": getattr(self, "memory_view_dialog", None),
            "mcp": getattr(self, "mcp_dialog", None),
            "skills": getattr(self, "open_skills_dialog", None),
            "settings": self.set_dialog,
        }.get(key)
        if callable(fn):
            fn()
            try:
                self.activity_bar.clearSelection()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _show_resources_menu(self):
        menu = QMenu(self)
        entries = (
            ("📚 知识库 / 资料", self.kb_dialog),
            ("🕒 历史记录", self.history_dialog),
            ("🧠 记忆", self.memory_view_dialog),
            ("🔍 搜索聊天", self.search_dialog),
            ("📊 数据统计", self.stats_dialog),
            ("🕸 知识图谱", self.graph_dialog),
        )
        for label, fn in entries:
            a = menu.addAction(label)
            a.triggered.connect(fn)
        menu.exec_(self.nav_list.mapToGlobal(self.nav_list.rect().bottomLeft()))

    @staticmethod
    def _add_menu_action(menu, seen_labels, seen_targets, label, fn):
        """添加菜单项，并按显示文字 + 实际回调双重去重。"""
        if not callable(fn) or label in seen_labels:
            return None
        target_key = getattr(fn, "__func__", fn)
        if target_key in seen_targets:
            return None
        seen_labels.add(label)
        seen_targets.add(target_key)
        action = menu.addAction(label)
        action.triggered.connect(fn)
        return action

    def _show_avatar_menu(self):
        """头像菜单只保留 5 项高频入口。

        其余功能全部放进更多；两个菜单不重复。
        """
        menu = QMenu(self)
        try:
            user = self.account.current_username() or "未登录"
        except Exception:  # 静默是故意的
            user = "未登录"
        head = menu.addAction(" %s" % user)
        head.setEnabled(False)
        menu.addSeparator()

        seen_labels, seen_targets = set(), set()
        mode_label = ("⚙ 切换模式：当前简单模式"
                      if getattr(self, "ui_mode_value", SIMPLE) == SIMPLE
                      else "⚙ 切换模式：当前高级模式")
        # 头像菜单固定 5 项：切换模式 / 检查更新 / 设置 / 登录 / 帮助
        self._add_menu_action(
            menu, seen_labels, seen_targets, mode_label, self._toggle_ui_mode)
        self._add_menu_action(
            menu, seen_labels, seen_targets, "🔄 检查更新", self.update_dialog)
        self._add_menu_action(
            menu, seen_labels, seen_targets, "⚙ 设置", self.set_dialog)
        self._add_menu_action(
            menu, seen_labels, seen_targets, "🔑 登录 / 切换账号",
            self.show_login)
        self._add_menu_action(
            menu, seen_labels, seen_targets, "❓ 帮助", self.show_tutorial)
        menu.exec_(self.avatar_btn.mapToGlobal(
            self.avatar_btn.rect().bottomLeft()))

    def _show_more_menu(self):
        """更多收纳其余所有入口，并按分组展示、自动去重。"""
        menu = QMenu(self)
        seen_labels, seen_targets = set(), set()
        # 头像菜单的 5 项不再出现在这里，避免重复。
        for group, feature_ids in MORE_MENU_GROUPS:
            # 先算这一组有哪些可调用入口，再决定是否加分组标题。
            entries = []
            for fid in feature_ids:
                feature = get_feature(fid)
                if feature is None:
                    continue
                fn = getattr(self, feature.action, None)
                if callable(fn):
                    entries.append(("%s %s" % (feature.icon, feature.label),
                                    fn))
            if not entries:
                continue
            menu.addSection(group)
            for label, fn in entries:
                self._add_menu_action(
                    menu, seen_labels, seen_targets, label, fn)
        menu.exec_(self.more_btn.mapToGlobal(
            self.more_btn.rect().bottomLeft()))
