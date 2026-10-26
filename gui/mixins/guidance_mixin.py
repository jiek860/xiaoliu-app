# -*- coding: utf-8 -*-
"""主窗口引导、模式切换、空状态和聊天动作。"""
from __future__ import annotations

import html

from PyQt5.QtCore import Qt
from core.feature_registry import ADVANCED, SIMPLE
from PyQt5.QtWidgets import QMessageBox

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class GuidanceMixin:
    def _apply_mode(self, mode=None):
        from gui.build_ui import apply_ui_mode
        return apply_ui_mode(self, mode)

    def _set_ui_mode(self, mode):
        try:
            mode = self.ui_mode.set_mode(mode)
        except Exception:  # 静默是故意的
            mode = ADVANCED if str(mode).lower() == ADVANCED else SIMPLE
        self._apply_mode(mode)
        self._refresh_guidance()
        try:
            self.statusBar().showMessage(
                "已切换到%s模式" % ("高级" if mode == ADVANCED else "简单"), 3000)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return mode

    def _toggle_ui_mode(self):
        target = ADVANCED if getattr(self, "ui_mode_value", SIMPLE) == SIMPLE \
            else SIMPLE
        return self._set_ui_mode(target)

    def _on_composer_mode_changed(self, index):
        if index == 1:
            self.input.setPlaceholderText(
                "描述一个目标，任务模式会拆解步骤、执行并显示结果")
            if getattr(self, "guidance_label", None) is not None:
                self.guidance_label.setText(
                    "任务模式：复杂目标会拆成计划，执行过程可在任务中心查看")
        else:
            self.input.setPlaceholderText(
                "说一句话，或者直接描述一个任务（Enter 发送）")
            self._refresh_guidance()
        try:
            self.send_btn.setText("开始任务" if index == 1 else "发送")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _set_composer_mode(self, mode):
        try:
            self.mode_combo.setCurrentIndex(1 if str(mode).startswith("task") else 0)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _composer_is_task(self):
        try:
            return self.mode_combo.currentIndex() == 1
        except Exception:  # 静默是故意的
            return False

    def _run_guide_card(self, index):
        try:
            cards = self.guidance.empty_state_cards()
            card = cards[int(index)]
            self._run_guidance_action(card.get("action"))
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "下一步", str(e)[:120])

    def _run_guidance_action(self, action, task_id=None):
        action = str(action or "")
        from gui.guidance import GUIDANCE
        if action in GUIDANCE:
            action = GUIDANCE[action]["action"]
        try:
            if action == "open_model_settings":
                return self.set_dialog()
            if action == "focus_input":
                self._set_composer_mode("chat")
                self.input.setFocus()
                return None
            if action == "start_task":
                return self.start_task()
            if action == "open_knowledge_base":
                return self.kb_dialog()
            if action == "open_security_center" or \
                    action == "open_security_network_events":
                return self.security_center_dialog()
            if action == "retry_failed_step":
                if task_id:
                    return self._retry_task(task_id)
                task = self._latest_task(("failed",))
                if task:
                    return self._retry_task(task.get("id"))
                return self.start_task()
            if action == "open_plugin_market":
                return self.plugin_dialog()
            if action == "increase_task_budget":
                if task_id:
                    return self._increase_task_budget(task_id)
                task = self._latest_task(("failed", "running", "paused"))
                if task:
                    return self._increase_task_budget(task.get("id"))
                self.chat.append_guidance_card(
                    "任务超时", "没有找到可继续的任务，先创建一个新任务。",
                    "guidance://start_task", "开始任务")
                return None
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "下一步", str(e)[:120])
        return None

    def _latest_task(self, statuses=()):
        try:
            tasks = self.trunk.get_task_runtime().list_tasks()
        except Exception:  # 静默是故意的
            return None
        wanted = set(statuses or ())
        for task in tasks:
            if not wanted or task.get("status") in wanted:
                return task
        return tasks[0] if tasks else None

    def _refresh_guidance(self):
        if not hasattr(self, "guidance"):
            return
        try:
            cards = self.guidance.empty_state_cards()
        except Exception:  # 静默是故意的
            cards = []
        for i, btn in enumerate(getattr(self, "guide_cards", []) or []):
            if i >= len(cards):
                btn.setVisible(False)
                continue
            card = cards[i]
            prefix = " " if card.get("done") else "%d. " % (i + 1)
            # 卡片是 QLabel + 富文本链接（不再用按钮，省按钮预算）
            btn.setText(
                '<a href="go" style="color:#344054;text-decoration:none;">'
                '%s%s<br/><span style="color:#1976d2;">%s</span></a>'
                % (prefix, html.escape(str(card.get("title", "下一步"))),
                   html.escape(str(card.get("action_label", "")))))
            btn.setToolTip(card.get("message", ""))
        try:
            current = self.guidance.current()
            self.guidance_label.setText(
                ("下一步：" + current.get("title", "")) if current else "")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        self._update_empty_state()

    def _update_empty_state(self):
        empty = getattr(self, "empty_state", None)
        if empty is None:
            return
        try:
            has_text = bool(self.chat.toPlainText().strip())
        except Exception:  # 静默是故意的
            has_text = False
        empty.setVisible(not has_text)

    def _mark_guide_event(self, event):
        try:
            self.guidance.mark_done(event)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        self._refresh_guidance()

    def _on_chat_action(self, url):
        u = str(url or "")
        if u.startswith("history://older"):
            return self._load_older_history()
        if u.startswith("task://"):
            return self.open_task_center(task_id=u[len("task://"):])
        if u.startswith("retry://"):
            return self._retry_task(u[len("retry://"):])
        # 聊天失败卡片上的「重试这条」：删掉上一轮再发同一条，
        # 不用用户自己复制粘贴
        if u.startswith("chat-retry://"):
            return self.regenerate_last_reply()
        if u.startswith("task-budget://"):
            return self._increase_task_budget(u[len("task-budget://"):])
        if u.startswith("settings://"):
            return self.set_dialog()
        if u.startswith("plugins://"):
            return self.plugin_dialog()
        if u.startswith("security://"):
            return self.security_center_dialog()
        if u.startswith("guidance://"):
            return self._run_guidance_action(u[len("guidance://"):])
        return None

    def _convert_to_task(self, text=None):
        text = (text or "").strip()
        if not text:
            QMessageBox.information(self, "转为任务", "请先输入目标或选中一段文字")
            return
        self._set_composer_mode("task")
        return self.start_task(goal=text, auto_start=True)
