# -*- coding: utf-8 -*-
"""工作台里的 AI 面板（AgentDock）。

从 gui/workbench_dialog.py 原样搬出（该文件接近 600 行上限）。
只搬代码不改行为：类名、方法名、界面结构与原来逐行一致。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QSpinBox, QVBoxLayout, QWidget)

from core.code_plan import plan_text

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


class AgentDock(QWidget):
    """AI 面板：目标输入 + 执行按钮 + 步骤时间线。

    不自己实现 Agent 逻辑，委托给 AgentOrchestrator / CodeAgent
    （与旧"Agent 旅程"用的是同一套能力层）。
    """

    def __init__(self, workbench):
        super().__init__()
        self.wb = workbench
        self.orchestrator = None
        self.queue = None
        self.current_job_id = ""
        self._running = False
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(4)

        head = QHBoxLayout()
        head.addWidget(QLabel("🤖 AI"))
        self.hint = QLabel("描述目标；会读取你当前打开的文件")
        self.hint.setStyleSheet("color:#667085;font-size:11px;")
        head.addWidget(self.hint, 1)
        head.addWidget(QLabel("轮次上限"))
        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(1, 15)
        try:
            from core.code_agent_policy import resolve_max_rounds
            self.rounds_spin.setValue(resolve_max_rounds(None, self.wb.trunk))
        except Exception:
            self.rounds_spin.setValue(12)
        self.rounds_spin.setToolTip("代码任务最多回修多少轮（默认 12）")
        head.addWidget(self.rounds_spin)
        self.expand_btn = QPushButton("⛶ 弹出")
        self.expand_btn.setFixedHeight(28)
        self.expand_btn.setToolTip("把 AI 面板弹出为独立窗口（可放到第二块屏幕）")
        self.expand_btn.clicked.connect(self.wb.toggle_ai_popup)
        head.addWidget(self.expand_btn)
        v.addLayout(head)

        self.goal = QPlainTextEdit()
        self.goal.setPlaceholderText("例如：给 main() 加上命令行参数解析，并跑测试")
        self.goal.setMaximumHeight(60)
        v.addWidget(self.goal)

        # 按钮横向排列：主操作靠左，"暂停/取消"紧挨着，避免竖排占高度。
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.clicked.connect(self.start)
        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        self.cancel_btn = QPushButton("🛑 取消")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        for b in (self.start_btn, self.pause_btn, self.cancel_btn):
            b.setFixedHeight(28)
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)

        v.addWidget(QLabel("任务队列（双击未完成任务可续跑）"))
        self.queue_list = QListWidget()
        self.queue_list.setMaximumHeight(64)
        self.queue_list.setToolTip("排队的代码任务；双击中断/失败任务从断点继续")
        self.queue_list.itemDoubleClicked.connect(self._resume_item)
        v.addWidget(self.queue_list)

        self.timeline = QPlainTextEdit()
        self.timeline.setReadOnly(True)
        self.timeline.setPlaceholderText("执行步骤会显示在这里")
        self.timeline.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas;font-size:12px;")
        v.addWidget(self.timeline, 1)

        foot = QHBoxLayout()
        self.open_with_agent = QCheckBox("把当前打开的文件交给 AI")
        self.open_with_agent.setChecked(True)
        foot.addWidget(self.open_with_agent)
        foot.addStretch(1)
        v.addLayout(foot)

    # ---------------------------------------------------------- 执行
    def current_goal(self):
        """当前目标文本（去首尾空白）。"""
        return self.goal.toPlainText().strip()

    def can_start(self):
        """是否满足启动条件（空目标不让点）。"""
        return bool(self.current_goal())

    def start(self):
        if self._running:
            self.timeline.appendPlainText("⚠ 已有任务在运行，请先暂停或取消")
            return
        goal = self.current_goal()
        if not goal:
            self.timeline.appendPlainText("⚠ 请先描述要做什么")
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        open_files = []
        if self.open_with_agent.isChecked():
            open_files = self.wb.editor_open_files()
        self.current_job_id = ""
        try:
            from core.code_task_queue import get_code_queue
            self.queue = get_code_queue(root)
            job = self.queue.enqueue(
                goal, max_rounds=self.rounds_spin.value(),
                open_files=open_files)
            self.current_job_id = job["job_id"]
            self._refresh_queue()
        except Exception as e:  # 静默是故意的 - 队列不可用也要能跑任务
            _x6_swallowed(__name__, e, "enqueue code job")
        self._run_job(goal, open_files=open_files)

    def _run_job(self, goal, open_files=None, resume_state=None):
        if self._running:
            self.timeline.appendPlainText("⚠ 已有任务在运行，请先暂停或取消")
            return
        try:
            from core.agent_orchestrator import AgentOrchestrator
        except Exception as e:
            self.timeline.appendPlainText("[错误] 无法加载 Agent: %s" % str(e)[:200])
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        open_files = list(open_files or [])
        rounds = self.rounds_spin.value()

        def make(**extra):
            return AgentOrchestrator(
                self.wb.trunk, root=root, event_cb=self._on_event,
                approval_cb=self._approve, **extra)

        try:
            self.orchestrator = make(open_files=open_files, max_code_rounds=rounds)
        except TypeError:
            try:
                self.orchestrator = make(open_files=open_files)
            except TypeError:
                self.orchestrator = make()
        if resume_state and self.current_job_id and self.queue:
            try:
                self.queue.mark_running(self.current_job_id)
                self._refresh_queue()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "mark job running")
        self.timeline.clear()
        self.timeline.appendPlainText("▶ 目标: " + goal)
        if resume_state:
            self.timeline.appendPlainText(
                "  ↯ 从第 %s 轮续跑" % (resume_state.get("round") or 1))
        if open_files:
            self.timeline.appendPlainText(
                "  参考文件: " + ", ".join(os.path.basename(f) for f in open_files))
        self.timeline.appendPlainText("  轮次上限: %d" % rounds)
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        def checkpoint(state):
            if self.queue and self.current_job_id:
                self.queue.checkpoint(self.current_job_id, state)
                self._refresh_queue()

        try:
            self._running = True
            result = self.orchestrator.run(
                goal, resume_state=resume_state or {}, checkpoint_cb=checkpoint)
            if self.queue and self.current_job_id:
                self.queue.mark_done(self.current_job_id, result)
                self._refresh_queue()
            self._on_done(result)
        except Exception as e:  # 静默是故意的 - 出错要显示给用户而不是崩
            self._running = False
            if self.queue and self.current_job_id:
                self.queue.mark_paused(self.current_job_id, str(e))
                self._refresh_queue()
            self.timeline.appendPlainText("[错误] %s" % str(e)[:300])
            self._reset_buttons()

    def _refresh_queue(self):
        """刷新队列列表：状态 + 轮次 + 目标摘要。"""
        try:
            self.queue_list.clear()
            if not self.queue:
                return
            icons = {"queued": "○", "running": "▶", "completed": "✓",
                     "failed": "✗", "paused": "⏸", "interrupted": "↯",
                     "cancelled": "■"}
            for job in list(reversed(self.queue.jobs()))[:20]:
                icon = icons.get(job.get("status"), "·")
                text = "%s 第%s轮 %s" % (
                    icon, int(job.get("round") or 0),
                    str(job.get("goal") or "")[:70])
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, job.get("job_id"))
                item.setToolTip("%s\n状态: %s\n停止原因: %s" % (
                    job.get("goal") or "", job.get("status"),
                    job.get("stop_reason") or job.get("error") or ""))
                self.queue_list.addItem(item)
        except Exception as e:  # 静默是故意的 - 列表刷新失败不影响执行
            _x6_swallowed(__name__, e, "refresh code queue")

    def _resume_item(self, item):
        """双击队列项：未完成的从断点续跑，其它只载入目标。"""
        if not self.queue:
            return
        job = self.queue.get(item.data(Qt.UserRole))
        if not job:
            return
        self.goal.setPlainText(job.get("goal") or "")
        state = self.queue.checkpoint_of(job)
        if job.get("status") in ("paused", "failed", "interrupted") and state:
            self.current_job_id = job.get("job_id")
            self.timeline.appendPlainText(
                "↯ 继续任务（从第 %s 轮）" % (state.get("round") or 1))
            self._run_job(job.get("goal") or "", open_files=job.get("open_files"),
                          resume_state=state)
        else:
            self.timeline.appendPlainText("已载入队列任务，可点击开始执行")

    def _on_done(self, result):
        self._running = False
        if isinstance(result, dict):
            if result.get("ok"):
                self.timeline.appendPlainText(
                    "✅ 完成（%s 轮，%s）" % (
                        result.get("rounds_used") or "-",
                        result.get("stop_reason") or "tests_green"))
            else:
                self.timeline.appendPlainText(
                    "⚠ 未完成[%s]: %s" % (
                        result.get("stop_reason") or "-",
                        str(result.get("error") or "")[:200]))
        self._reset_buttons()

    def _reset_buttons(self):
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸ 暂停")
        self.cancel_btn.setEnabled(False)

    def _on_event(self, event, data=None):
        from PyQt5.QtWidgets import QApplication
        text = str(event or "")
        if isinstance(data, dict):
            text = str(data.get("step") or text)
        self.timeline.appendPlainText("· " + text[:300])
        data = data if isinstance(data, dict) else {}
        if event == "plan" and isinstance(data.get("plan"), dict):
            self.timeline.appendPlainText(plan_text(data["plan"]))
        if event == "patch" and isinstance(data.get("patch"), dict):
            self._show_inline_diff(data["patch"])
        elif event == "applied":
            for rel in data.get("applied") or []:
                try:
                    self.wb.reload_editor_path(rel)
                except Exception as e:  # 静默是故意的 - 刷新失败不影响主流程
                    _x6_swallowed(__name__, e, "reload editor tab")
            self.wb.mark_diff_applied(data.get("backup_manifest") or "")
        QApplication.processEvents()      # 让界面边跑边刷

    def _show_inline_diff(self, patch):
        """在编辑器里展示内联 diff；应用后用 backup manifest 撤销。"""
        try:
            editor = getattr(self.wb, "_editor", None)
            if editor is None or not hasattr(editor, "show_diff_preview"):
                return
            root = getattr(self.wb, "root", None) or "."
            return editor.show_diff_preview(root, patch)
        except Exception as e:  # 静默是故意的 - 预览失败不影响任务执行
            _x6_swallowed(__name__, e, "show inline diff")

    def _approve(self, kind, payload=None):
        """计划 / diff / 电脑动作审批。"""
        try:
            from gui.diff_dialog import DiffReviewDialog
            if kind == "plan":
                r = QMessageBox.question(
                    self, "执行计划", plan_text(payload or {}),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                return r == QMessageBox.Yes
            if kind == "code" and isinstance(payload, dict):
                from core.patch_engine import unified_diff
                root = getattr(self.wb, "root", None) or "."
                text = unified_diff(root, payload)
            else:
                text = str(payload or "")
            dlg = DiffReviewDialog(text, parent=self)
            return dlg.exec_() == dlg.Accepted
        except Exception as e:  # 静默是故意的 - 审批打不开就拒绝，fail-closed
            _x6_swallowed(__name__, e, "best-effort fallback")
            return False

    def toggle_pause(self):
        if self.orchestrator is None:
            return
        try:
            if self.pause_btn.text().startswith("⏸"):
                self.orchestrator.pause()
                self.pause_btn.setText("▶ 继续")
                self.timeline.appendPlainText("⏸ 已暂停")
            else:
                self.orchestrator.resume()
                self.pause_btn.setText("⏸ 暂停")
                self.timeline.appendPlainText("▶ 已继续")
        except Exception as e:  # 静默是故意的
            self.timeline.appendPlainText("[错误] %s" % str(e)[:200])

    def cancel(self):
        if self.orchestrator is None:
            return
        try:
            self.orchestrator.cancel()
            self.timeline.appendPlainText("🛑 已取消")
            if self.queue and self.current_job_id:
                self.queue.mark_paused(self.current_job_id, "用户取消")
                self._refresh_queue()
        except Exception as e:  # 静默是故意的
            self.timeline.appendPlainText("[错误] %s" % str(e)[:200])
        self._reset_buttons()
