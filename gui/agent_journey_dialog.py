# -*- coding: utf-8 -*-
"""统一 Agent 旅程窗口：一个输入框，自动路由到代码/电脑/对话。

统一提供：
* 实时步骤时间线；
* 暂停 / 继续 / 取消 / 人工接管；
* 代码 diff 审批与电脑动作审批；
* 一键回滚。
"""
from __future__ import annotations

import os
import threading

from PyQt5.QtCore import QThread, pyqtSignal, QObject, Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QComboBox, QMessageBox, QFileDialog,
)

from core.agent_orchestrator import AgentOrchestrator
from core.code_plan import plan_text
from gui.agent_timeline import AgentTimeline
from gui.diff_dialog import DiffReviewDialog


class _Bridge(QObject):
    event = pyqtSignal(str, object)
    approval = pyqtSignal(str, object)
    done = pyqtSignal(object)


class _JourneyWorker(QThread):
    def __init__(self, trunk, goal, root, explicit=None, parent=None,
                 open_files=None, selection=""):
        super().__init__(parent)
        self.trunk = trunk
        self.goal = goal
        self.root = root
        self.explicit = explicit
        self.open_files = list(open_files or [])
        self.selection = str(selection or "")
        self.bridge = _Bridge()
        self.orchestrator = None
        self._approval_event = None
        self._approval_result = False
        self._closed = False

    def run(self):
        try:
            self.orchestrator = AgentOrchestrator(
                self.trunk, root=self.root,
                event_cb=lambda e, d: self.bridge.event.emit(e, d),
                approval_cb=self._approve,
                open_files=self.open_files,
                selection=self.selection)
            result = self.orchestrator.run(
                self.goal, explicit=self.explicit,
                event_cb=lambda e, d: self.bridge.event.emit(e, d),
                approval_cb=self._approve)
        except Exception as e:
            result = {"ok": False, "error": str(e)[:500]}
        try:
            self.bridge.done.emit(result)
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass

    def _approve(self, kind, payload):
        if self._closed:
            return False
        self._approval_result = False
        self._approval_event = threading.Event()
        self.bridge.approval.emit(kind, payload)
        if not self._approval_event.wait(600):
            return False
        return self._approval_result

    def resolve_approval(self, result):
        self._approval_result = result
        if self._approval_event is not None:
            self._approval_event.set()

    def cancel_from_ui(self):
        self._closed = True
        if self.orchestrator is not None:
            self.orchestrator.cancel()
        self.resolve_approval(False)


class AgentJourneyDialog(QDialog):
    def __init__(self, trunk, parent=None, root=None, open_files=None,
                 selection=""):
        super().__init__(parent)
        self.trunk = trunk
        self.root = os.path.abspath(root or getattr(trunk, "base", "."))
        self.open_files = list(open_files or [])
        self.selection = str(selection or "")
        self.worker = None
        self._paused = False
        self._close_pending = False
        self.setWindowTitle("Agent 旅程")
        self.resize(1080, 760)
        self._build()
        self._update_route_preview()

    def _build(self):
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("目标"))
        self.goal = QPlainTextEdit()
        self.goal.setPlaceholderText(
            "直接描述目标，例如：\n"
            " 修复设置窗口保存失败并补测试\n"
            " 打开浏览器搜索今天的天气，把结果保存到记事本")
        self.goal.setMaximumHeight(86)
        self.goal.textChanged.connect(self._update_route_preview)
        top.addWidget(self.goal, 1)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.addWidget(QLabel("路由"))
        self.route_combo = QComboBox()
        self.route_combo.addItem("自动判断", None)
        self.route_combo.addItem("代码 Agent", "code")
        self.route_combo.addItem("电脑 Agent", "computer")
        self.route_combo.addItem("普通对话", "chat")
        self.route_combo.currentIndexChanged.connect(self._update_route_preview)
        row.addWidget(self.route_combo)
        self.route_label = QLabel("")
        self.route_label.setStyleSheet("color:#667085;font-size:12px;")
        row.addWidget(self.route_label, 1)
        self.root_btn = QPushButton("项目目录")
        self.root_btn.clicked.connect(self._choose_root)
        row.addWidget(self.root_btn)
        lay.addLayout(row)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton("开始执行")
        self.start_btn.clicked.connect(self._start)
        buttons.addWidget(self.start_btn)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        buttons.addWidget(self.pause_btn)
        self.takeover_btn = QPushButton("人工接管")
        self.takeover_btn.setEnabled(False)
        self.takeover_btn.clicked.connect(self._takeover)
        buttons.addWidget(self.takeover_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_btn)
        self.rollback_btn = QPushButton("一键撤销")
        self.rollback_btn.setEnabled(False)
        self.rollback_btn.clicked.connect(self._rollback)
        buttons.addWidget(self.rollback_btn)
        buttons.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        lay.addLayout(buttons)

        self.timeline = AgentTimeline()
        lay.addWidget(self.timeline, 1)

    def _choose_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择代码项目目录", self.root)
        if d:
            self.root = os.path.abspath(d)
            self.route_label.setText("项目目录：%s" % self.root)

    def _update_route_preview(self):
        goal = self.goal.toPlainText().strip()
        explicit = self.route_combo.currentData()
        try:
            orch = AgentOrchestrator(self.trunk, root=self.root)
            info = orch.describe(goal or "你好")
            if explicit:
                info["kind"] = explicit
                info["label"] = {
                    "code": "代码 Agent", "computer": "电脑 Agent",
                    "chat": "普通对话"}.get(explicit, "自动")
                info["reason"] = "手动指定"
            self.route_label.setText(
                "将使用：%s（%s）项目：%s" % (
                    info.get("label") or info.get("kind"),
                    info.get("reason", ""), self.root))
        except Exception as e:
            self.route_label.setText("路由预览失败：" + str(e)[:120])

    def _start(self):
        goal = self.goal.toPlainText().strip()
        if not goal:
            QMessageBox.information(self, "Agent 旅程", "请先输入目标")
            return
        self.timeline.clear()
        self.timeline.set_status("正在启动 Agent", "running")
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.takeover_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.rollback_btn.setEnabled(False)
        self._paused = False
        self.pause_btn.setText("暂停")
        self.worker = _JourneyWorker(
            self.trunk, goal, self.root,
            explicit=self.route_combo.currentData(), parent=self,
            open_files=self.open_files, selection=self.selection)
        self.worker.bridge.event.connect(self._on_event)
        self.worker.bridge.approval.connect(self._on_approval)
        self.worker.bridge.done.connect(self._on_done)
        self.worker.start()

    def _on_event(self, event, data):
        data = data or {}
        step = str(data.get("step") or event)
        state = "running"
        low = str(event).lower()
        if any(k in low for k in ("done", "complete", "step_done")):
            state = "done" if data.get("ok", True) else "failed"
        elif any(k in low for k in ("failed", "error")):
            state = "failed"
        elif any(k in low for k in ("cancel",)):
            state = "cancelled"
        elif any(k in low for k in ("approval", "pause")):
            state = "waiting"
        self.timeline.set_status(step, state)
        if isinstance(data.get("progress"), (int, float)):
            self.timeline.set_progress(data.get("progress"))
        if event == "plan" and isinstance(data.get("plan"), dict):
            self.timeline.add_step("执行计划", plan_text(data["plan"]), "waiting")
            return
        detail_parts = []
        for k in ("thought", "result", "verify", "error", "reason",
                  "output", "files", "applied"):
            if k in data and data.get(k) not in (None, "", [], {}):
                detail_parts.append("%s: %s" % (k, data.get(k)))
        detail = "\n".join(detail_parts)[:5000]
        status = state
        if event == "route":
            self.timeline.add_step(step, detail, "done")
        elif event in ("observe", "model_request", "tool_result", "context"):
            self.timeline.add_step(step, detail or str(data)[:3000], "running")
        elif event in ("step_start", "tests_start", "apply"):
            self.timeline.add_step(step, detail, "running")
        elif event in ("step_done", "applied", "done"):
            self.timeline.add_step(
                step, detail, "done" if data.get("ok", True) else "failed")
        elif event in ("failed", "test_failed", "cancelled"):
            self.timeline.add_step(step, detail, "failed")
        elif event == "retry":
            self.timeline.add_step(step, detail, "waiting")
        else:
            self.timeline.add_step(step, detail, status)
        shot = data.get("screenshot") or data.get("after_screenshot")
        if shot:
            self.timeline.show_screenshot(shot)

    def _on_approval(self, kind, payload):
        if kind == "plan":
            r = QMessageBox.question(
                self, "执行计划", plan_text(payload or {}),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            result = (r == QMessageBox.Yes)
        elif kind == "code":
            try:
                dlg = DiffReviewDialog(
                    self.root, payload, self, apply_on_accept=False)
                dlg.exec_()
                approved = dlg.accepted
                result = {
                    "accepted": approved,
                    "selected_files": dlg.selected_files or [],
                    "selected_hunks": dlg.selected_hunks or [],
                }
            except Exception as e:
                QMessageBox.warning(self, "代码修改审批", str(e)[:300])
                result = {"accepted": False}
        else:
            lines = []
            for a in payload or []:
                lines.append(" [%s] %s" % (
                    (a or {}).get("risk", "?"),
                    (a or {}).get("reason") or (a or {}).get("type", "")))
            text = "Agent 准备执行以下电脑动作：\n\n" + "\n".join(lines[:30])
            r = QMessageBox.question(
                self, "电脑动作审批", text,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            result = (r == QMessageBox.Yes)
        self.worker.resolve_approval(result)
        self.timeline.set_status("审批已处理", "running")

    def _on_done(self, result):
        result = result or {}
        if self._close_pending:
            self._close_pending = False
            QTimer.singleShot(0, self.close)
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.takeover_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.rollback_btn.setEnabled(bool(result.get("backups") or
                                          result.get("run_id")))
        if result.get("ok"):
            self.timeline.set_status("任务完成", "done")
            self.timeline.set_progress(1.0)
            if result.get("kind") == "chat":
                self.timeline.add_step(
                    "对话完成", result.get("answer", ""), "done")
        elif result.get("cancelled"):
            self.timeline.set_status("任务已取消", "cancelled")
        else:
            self.timeline.set_status(
                "任务失败：" + str(result.get("error") or "")[:200], "failed")
            self.timeline.append_detail(
                "失败原因", str(result.get("error") or result)[:4000])

    def _toggle_pause(self):
        if not self.worker or not self.worker.orchestrator:
            return
        if self._paused:
            self.worker.orchestrator.resume()
            self._paused = False
            self.pause_btn.setText("暂停")
            self.timeline.set_status("继续执行", "running")
        else:
            self.worker.orchestrator.pause()
            self._paused = True
            self.pause_btn.setText("继续")
            self.timeline.set_status("已暂停", "waiting")

    def _takeover(self):
        if not self.worker or not self.worker.orchestrator:
            return
        self.worker.orchestrator.pause()
        self._paused = True
        self.pause_btn.setText("继续")
        QMessageBox.information(
            self, "人工接管",
            "Agent 已暂停。现在你可以手动操作电脑或修改文件。\n"
            "完成后点「继续」，Agent 会重新观察当前屏幕再决定下一步。")

    def _cancel(self):
        if self.worker:
            self.worker.cancel_from_ui()
        self.timeline.set_status("正在取消", "cancelled")

    def _rollback(self):
        if not self.worker or not self.worker.orchestrator:
            return
        r = self.worker.orchestrator.rollback()
        if r.get("ok"):
            self.timeline.set_status("已撤销", "done")
            self.timeline.append_detail(
                "回滚结果", "已恢复：%s" % (r.get("restored") or []))
        else:
            QMessageBox.warning(self, "撤销失败", str(r.get("error") or r)[:300])

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            r = QMessageBox.question(
                self, "任务仍在运行",
                "关闭窗口会取消当前任务，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel_from_ui()
            self.worker.wait(3000)
            if self.worker.isRunning():
                self._close_pending = True
                self.hide()
                QMessageBox.information(
                    self, "正在后台停止",
                    "任务已请求取消，仍在等待底层系统调用返回。\n"
                    "窗口已隐藏，线程安全退出后会自动关闭。")
                event.ignore()
                return
        event.accept()
