# -*- coding: utf-8 -*-
"""电脑 Agent 对话框：目标 -> LLM 跨应用计划 -> 确认 -> 执行/验证。"""
from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QMessageBox,
)

from core.action_schema import action_summary
from core.computer_agent import ComputerAgent
from gui.agent_timeline import AgentTimeline
from gui.feedback_states import make_action_links


class _EventBridge(QObject):
    event = pyqtSignal(str, object)


class _PlanWorker(QThread):
    done = pyqtSignal(object)
    def __init__(self, agent, goal):
        super().__init__()
        self.agent = agent
        self.goal = goal
    def run(self):
        try:
            snap = self.agent.observe()
            actions = self.agent.plan_goal(self.goal, snap)
            self.done.emit({"ok": True, "actions": actions, "snapshot": {
                "active_window": snap.get("active_window", ""),
                "elements": len(snap.get("elements") or []),
                "screenshot": snap.get("screenshot", ""),
            }})
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)[:500]})


class _RunWorker(QThread):
    done = pyqtSignal(object)
    def __init__(self, agent, actions, goal):
        super().__init__()
        self.agent = agent
        self.actions = actions
        self.goal = goal
    def run(self):
        try:
            # 真正执行时使用动态循环：每一步重新观察，失败后重新规划。
            self.done.emit(self.agent.run_goal_dynamic(
                self.goal, max_steps=12))
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)[:500]})


class ComputerAgentDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.agent = ComputerAgent(trunk)
        self.actions = []
        self._worker = None
        self._bridge = _EventBridge(self)
        self._bridge.event.connect(self._on_agent_event)
        self._paused = False
        self._last_run_id = ""
        self._close_pending = False
        self.setWindowTitle("电脑 Agent")
        self.resize(860, 640)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("目标："))
        self.goal = QLineEdit()
        self.goal.setPlaceholderText(
            "例如：打开浏览器搜索今天的天气，并把结果保存到记事本")
        lay.addWidget(self.goal)
        row = QHBoxLayout()
        self.plan_btn = QPushButton("生成跨应用计划")
        self.plan_btn.clicked.connect(self._plan)
        row.addWidget(self.plan_btn)
        self.run_btn = QPushButton("执行计划")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run)
        row.addWidget(self.run_btn)
        self.pause_btn = make_action_links(
            [("⏸ 暂停 / 继续", self._toggle_pause)])
        self.pause_btn.setEnabled(False)
        row.addWidget(self.pause_btn)
        self.takeover_btn = make_action_links(
            [("🖐 人工接管", self._takeover)])
        self.takeover_btn.setEnabled(False)
        row.addWidget(self.takeover_btn)
        self.cancel_btn = make_action_links([("✖ 取消任务", self._cancel)])
        self.cancel_btn.setEnabled(False)
        row.addWidget(self.cancel_btn)
        self.rollback_btn = make_action_links(
            [("↩ 一键撤销文件操作", self._rollback)])
        self.rollback_btn.setEnabled(False)
        row.addWidget(self.rollback_btn)
        row.addStretch(1)
        # 关闭交给 Esc / 右上角：又多一个"关闭"按钮只会挤掉主操作。
        row.addWidget(QLabel("Esc 关闭"))
        lay.addLayout(row)
        self.timeline = AgentTimeline()
        lay.addWidget(self.timeline, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(110)
        self.output.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        self.output.setPlainText(
            "流程：观察屏幕 -> 单步规划 -> 执行 -> 验证 -> 重新观察/重规划。"
            "可暂停、人工接管、取消和一键撤销文件操作。")
        lay.addWidget(self.output)

    def _plan(self):
        goal = self.goal.text().strip()
        if not goal:
            QMessageBox.information(self, "电脑 Agent", "请先输入目标")
            return
        self.plan_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.actions = []
        self.output.appendPlainText("\n>>> 正在观察屏幕并生成计划")
        self.agent.event_cb = self._bridge.event.emit
        self._worker = _PlanWorker(self.agent, goal)
        self._worker.done.connect(self._on_plan)
        self._worker.start()

    def _on_plan(self, result):
        self.plan_btn.setEnabled(True)
        if not result.get("ok"):
            self.output.appendPlainText("[失败] " + result.get("error", "计划失败"))
            return
        self.actions = result.get("actions") or []
        snap = result.get("snapshot") or {}
        self.output.appendPlainText(
            "当前窗口：%s；控件候选：%s" %
            (snap.get("active_window", ""), snap.get("elements", 0)))
        self.output.appendPlainText("计划：")
        for i, a in enumerate(self.actions, 1):
            self.output.appendPlainText(
                "  %d. [%s] %s" % (i, a.get("risk", "?"),
                                   action_summary(a)))
        self.run_btn.setEnabled(bool(self.actions))
        # 让人先看见"要动的那个屏幕"再决定执行：高风险动作光看文字不够。
        shot = snap.get("screenshot")
        if shot:
            self.timeline.show_screenshot(shot)
        high = [a for a in self.actions if a.get("risk") == "high"]
        if high:
            self.output.appendPlainText(
                "⚠ 其中 %d 个是高风险动作，执行前会再确认一次" % len(high))

    def _run(self):
        if not self.actions:
            return
        high = [a for a in self.actions if a.get("risk") == "high"]
        if high:
            r = QMessageBox.question(
                self, "高风险电脑操作",
                "计划里有 %d 个高风险动作，确定执行吗？" % len(high),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self.run_btn.setEnabled(False)
        self.output.appendPlainText("\n>>> 开始执行（失败会自动重新观察和规划）")
        self.pause_btn.setEnabled(True)
        self.takeover_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.rollback_btn.setEnabled(False)
        self._paused = False
        self.timeline.set_status("开始执行电脑任务", "running")
        self._worker = _RunWorker(self.agent, self.actions,
                                  self.goal.text().strip())
        self._worker.done.connect(self._on_run)
        self._worker.start()

    def _on_agent_event(self, event, data):
        data = data or {}
        step = str(data.get("step") or event)
        state = "running"
        low = str(event).lower()
        if any(k in low for k in ("done", "step_done")):
            state = "done" if data.get("ok", True) else "failed"
        if any(k in low for k in ("failed", "error")):
            state = "failed"
        if "cancel" in low:
            state = "cancelled"
        if any(k in low for k in ("approval", "retry", "pause")):
            state = "waiting"
        self.timeline.set_status(step, state)
        if isinstance(data.get("progress"), (int, float)):
            self.timeline.set_progress(data.get("progress"))
        detail = "\n".join("%s: %s" % (k, data[k]) for k in
                           ("thought", "result", "verify", "error", "reason",
                            "action", "attempts") if data.get(k))
        self.timeline.add_step(step, detail, state)
        shot = data.get("screenshot") or data.get("after_screenshot")
        if shot:
            self.timeline.show_screenshot(shot)

    def _toggle_pause(self):
        if self._paused:
            self.agent.resume()
            self._paused = False
            self.timeline.set_status("继续执行", "running")
        else:
            self.agent.pause()
            self._paused = True
            self.timeline.set_status("已暂停", "waiting")

    def _takeover(self):
        self.agent.pause()
        self._paused = True
        QMessageBox.information(
            self, "人工接管",
            "Agent 已暂停。现在可以手动操作电脑；完成后点「暂停 / 继续」，"
            "Agent 会重新观察当前屏幕再继续。")

    def _cancel(self):
        try:
            self.agent.cancel()
            self.timeline.set_status("正在取消", "cancelled")
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass

    def _rollback(self):
        r = self.agent.rollback_run(self._last_run_id)
        self.timeline.set_status("已撤销电脑文件操作", "done")
        self.timeline.append_detail(
            "回滚结果", "已恢复：%s" % (r.get("restored") or []))
        self.rollback_btn.setEnabled(False)

    def _on_run(self, result):
        self.run_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.takeover_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._last_run_id = result.get("run_id", "")
        self.rollback_btn.setEnabled(bool(
            result.get("rollback_items") or result.get("run_id")))
        if result.get("ok"):
            self.output.appendPlainText("[完成] 所有动作已执行并验证")
            self.timeline.set_status("电脑任务完成", "done")
            self.timeline.set_progress(1.0)
        else:
            self.output.appendPlainText(
                "[停止] " + str(result.get("error") or "动作失败"))
            self.timeline.set_status(
                "电脑任务失败：" + str(result.get("error") or "")[:160],
                "failed")
        for item in result.get("trace") or []:
            a = item.get("action") or {}
            v = item.get("verified") or {}
            self.output.appendPlainText(
                "- %s | 验证: %s | 重试: %s | 修复: %s" % (
                    action_summary(a), v.get("reason", ""), item.get("attempts", 0),
                    item.get("repair") or ""))

    def _maybe_finish_close(self):
        worker = self._worker
        if self._close_pending and worker is not None and not worker.isRunning():
            self._close_pending = False
            self.close()

    def closeEvent(self, event):
        w = self._worker
        if w is None or not w.isRunning():
            event.accept()
            return
        r = QMessageBox.question(
            self, "电脑任务仍在运行",
            "关闭窗口会取消当前电脑任务，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            event.ignore()
            return
        try:
            self.agent.cancel()
        except Exception:  # 静默是故意的 - 关闭流程尽力取消
            pass
        try:
            w.wait(3000)
        except Exception:  # 静默是故意的 - 关闭流程尽力等待
            pass
        if w.isRunning():
            self._close_pending = True
            try:
                w.finished.connect(self._maybe_finish_close)
            except Exception:  # 静默是故意的 - 信号连接失败不影响隐藏窗口
                pass
            self.hide()
            QMessageBox.information(
                self, "正在后台停止",
                "任务已请求取消，仍在等待当前系统调用返回。\n"
                "窗口已隐藏，线程安全退出后会自动关闭。")
            event.ignore()
            return
        event.accept()

