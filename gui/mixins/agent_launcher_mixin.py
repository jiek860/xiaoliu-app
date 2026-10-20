# -*- coding: utf-8 -*-
"""主窗口 Agent/活动中心/命令面板入口。"""
from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class AgentLauncherMixin:
    def computer_agent_dialog(self):
        try:
            from gui.computer_agent_dialog import ComputerAgentDialog
            d = ComputerAgentDialog(self.trunk, self)
            if not hasattr(self, "_computer_agent_dialogs"):
                self._computer_agent_dialogs = []
            self._computer_agent_dialogs.append(d)
            d.show()
            d.raise_()
            return d
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "电脑 Agent", "打不开：" + str(e)[:120])
            return None

    def agent_journey_dialog(self, goal=None):
        """统一 Agent 入口：一个输入框自动路由到代码/电脑/对话。"""
        try:
            from gui.agent_journey_dialog import AgentJourneyDialog
            d = AgentJourneyDialog(self.trunk, self, self.base)
            if goal:
                try:
                    d.goal.setPlainText(str(goal))
                except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                    _x6_swallowed(__name__, e, "best-effort fallback")
            if not hasattr(self, "_agent_journey_dialogs"):
                self._agent_journey_dialogs = []
            self._agent_journey_dialogs.append(d)
            d.show()
            d.raise_()
            return d
        except Exception as e:
            QMessageBox.warning(self, "Agent 旅程", "打不开：" + str(e)[:120])
            return None

    def code_agent_dialog(self):
        try:
            from gui.code_agent_dialog import CodeAgentDialog
            d = CodeAgentDialog(self.trunk, self, self.base)
            if not hasattr(self, "_code_agent_dialogs"):
                self._code_agent_dialogs = []
            self._code_agent_dialogs.append(d)
            d.show()
            d.raise_()
            return d
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "代码 Agent", "打不开：" + str(e)[:120])
            return None

    def _set_command_palette_shortcut(self, text):
        """即时安装新的命令面板快捷键，返回是否成功。"""
        text = str(text or "").strip() or "Ctrl+K"
        try:
            from PyQt5.QtWidgets import QShortcut
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtCore import Qt
            old = getattr(self, "_cmd_shortcut", None)
            if old is not None:
                try:
                    old.setEnabled(False)
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "best-effort fallback")
            sc = QShortcut(QKeySequence(text), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self.command_palette)
            self._cmd_shortcut = sc
            return True
        except Exception:  # 静默是故意的
            return False

    def activity_center_dialog(self):
        """统一查看运行中任务、后台活动和等待确认。"""
        try:
            from gui.activity_center_dialog import ActivityCenterDialog
            d = ActivityCenterDialog(self.trunk, self)
            if not hasattr(self, "_activity_centers"):
                self._activity_centers = []
            self._activity_centers.append(d)
            d.show()
            d.raise_()
            return d
        except Exception as e:
            QMessageBox.warning(self, "活动中心", "打不开：" + str(e)[:120])
            return None

    def _refresh_activity_badge(self):
        """状态栏显示运行中数量；点击打开活动中心。"""
        try:
            from core.agent_harness import get_run_registry
            n = get_run_registry().active_count()
            if getattr(self, "activity_btn", None) is not None:
                self.activity_btn.setText("运行中 %d" % n)
                self.activity_btn.setToolTip(
                    "运行中任务/后台活动：%d\n点击打开活动中心" % n)
                self.activity_btn.setStyleSheet(
                    "QPushButton{background:%s;color:%s;border:none;"
                    "border-radius:8px;padding:2px 9px;font-size:11px;}"
                    "QPushButton:hover{opacity:.85;}"
                    % (("#e8f5e9", "#15803d") if n else ("#f5f6f8", "#667085")))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
