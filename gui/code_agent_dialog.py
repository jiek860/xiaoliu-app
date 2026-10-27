# -*- coding: utf-8 -*-
"""代码 Agent 对话框：目标 -> patch 预览审批 -> 应用 -> 跑测试。"""
from __future__ import annotations

import os

from PyQt5.QtCore import QThread, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QFileDialog, QMessageBox,
)

from core.code_agent import CodeAgent
from gui.diff_dialog import DiffReviewDialog
from gui.agent_timeline import AgentTimeline
from gui.feedback_states import make_action_links


class _EventBridge(QObject):
    event = pyqtSignal(str, object)


class _PrepareWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, agent, goal, previous_error=""):
        super().__init__()
        self.agent = agent
        self.goal = goal
        self.previous_error = previous_error

    def run(self):
        try:
            self.done.emit(self.agent.prepare(self.goal, self.previous_error))
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e)[:500]})


class _TestWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, agent):
        super().__init__()
        self.agent = agent

    def run(self):
        try:
            tests = self.agent.run_tests()
            lint = self.agent.run_lint()
            self.done.emit({"ok": bool(tests.get("ok") and lint.get("ok")),
                            "tests": tests, "lint": lint})
        except Exception as e:
            self.done.emit({"ok": False, "tests": {"results": [{"output": str(e)}]},
                            "lint": {"results": []}})


class CodeAgentDialog(QDialog):
    def __init__(self, trunk, parent=None, root=None):
        super().__init__(parent)
        self.trunk = trunk
        self.root = os.path.abspath(root or getattr(trunk, "base", "."))
        self.agent = CodeAgent(trunk, self.root)
        self._worker = None
        self._test_worker = None
        self._bridge = _EventBridge(self)
        self._bridge.event.connect(self._on_agent_event)
        self._backups = []
        self._paused = False
        self._close_pending = False
        self.setWindowTitle("代码 Agent")
        self.resize(860, 620)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("项目目录："))
        row = QHBoxLayout()
        self.root_edit = QLineEdit(self.root)
        row.addWidget(self.root_edit, 1)
        row.addWidget(make_action_links([("📂 选择目录", self._choose_root)]))
        lay.addLayout(row)

        lay.addWidget(QLabel("目标："))
        self.goal = QLineEdit()
        self.goal.setPlaceholderText(
            "例如：修复设置窗口保存失败，并补一个测试")
        lay.addWidget(self.goal)

        lay.addWidget(QLabel("测试命令（可选，一行一个）："))
        self.test_cmd = QLineEdit()
        self.test_cmd.setPlaceholderText(
            '留空则自动运行当前 Python 的 pytest；例如：pytest tests/test_x.py -q')
        lay.addWidget(self.test_cmd)
        lay.addWidget(QLabel("Lint 命令（可选，一行一个）："))
        self.lint_cmd = QLineEdit()
        self.lint_cmd.setPlaceholderText(
            "例如：ruff check .；留空则不跑 lint")
        lay.addWidget(self.lint_cmd)

        btns = QHBoxLayout()
        self.run_btn = QPushButton("生成修改预览")
        self.run_btn.clicked.connect(self._start)
        btns.addWidget(self.run_btn)
        # 其余都是"有就点一下"的次要动作，做成链接，不再占按钮位
        self.fix_btn = make_action_links(
            [("🔧 基于失败输出继续修复", self._continue_fix)])
        self.fix_btn.hide()
        btns.addWidget(self.fix_btn)
        self.pause_btn = make_action_links([("⏸ 暂停 / 继续", self._toggle_pause)])
        self.pause_btn.setEnabled(False)
        btns.addWidget(self.pause_btn)
        self.cancel_btn = make_action_links([("✖ 取消任务", self._cancel)])
        self.cancel_btn.setEnabled(False)
        btns.addWidget(self.cancel_btn)
        self.rollback_btn = make_action_links(
            [("↩ 一键撤销全部修改", self._rollback)])
        self.rollback_btn.setEnabled(False)
        btns.addWidget(self.rollback_btn)
        btns.addStretch(1)
        btns.addWidget(QLabel("Esc 关闭"))
        lay.addLayout(btns)

        self.timeline = AgentTimeline()
        lay.addWidget(self.timeline, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(110)
        self.output.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        self.output.setPlainText(
            "流程：生成 patch -> 文件/hunk 审批 -> 应用 -> 跑测试。\n"
            "所有修改都可以点「一键撤销」回滚。")
        lay.addWidget(self.output)

    def _choose_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择项目目录", self.root)
        if d:
            self.root = os.path.abspath(d)
            self.root_edit.setText(self.root)
            self.agent = CodeAgent(
                self.trunk, self.root,
                event_cb=self._bridge.event.emit)

    def _start(self):
        goal = self.goal.text().strip()
        if not goal:
            QMessageBox.information(self, "代码 Agent", "请先输入目标")
            return
        self._goal = goal
        self._last_error = ""
        self.fix_btn.hide()
        self._begin_prepare(goal, "")

    def _continue_fix(self):
        goal = getattr(self, "_goal", "") or self.goal.text().strip()
        if not goal:
            return
        self.fix_btn.hide()
        self._begin_prepare(goal, getattr(self, "_last_error", ""))

    def _begin_prepare(self, goal, previous_error):
        cmds = [x.strip() for x in self.test_cmd.text().splitlines()
                if x.strip()]
        lints = [x.strip() for x in self.lint_cmd.text().splitlines()
                 if x.strip()]
        self.agent = CodeAgent(
            self.trunk, self.root, test_commands=cmds,
            lint_commands=lints, event_cb=self._bridge.event.emit)
        self.run_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.rollback_btn.setEnabled(False)
        self._paused = False
        self.timeline.set_status("正在分析项目并生成 patch", "running")
        self.output.appendPlainText("\n>>> 正在分析项目并生成 patch")
        self._worker = _PrepareWorker(self.agent, goal, previous_error)
        self._worker.done.connect(self._on_prepared)
        self._worker.start()

    def _on_agent_event(self, event, data):
        data = data or {}
        step = str(data.get("step") or event)
        state = "running"
        low = str(event).lower()
        if any(k in low for k in ("done", "step_done", "applied")):
            state = "done" if data.get("ok", True) else "failed"
        if any(k in low for k in ("failed", "error", "test_failed")):
            state = "failed"
        if "cancel" in low:
            state = "cancelled"
        self.timeline.set_status(step, state)
        if isinstance(data.get("progress"), (int, float)):
            self.timeline.set_progress(data.get("progress"))
        detail = "\n".join("%s: %s" % (k, data[k]) for k in
                           ("result", "verify", "error", "output", "files",
                            "applied", "restored") if data.get(k))
        self.timeline.add_step(step, detail, state)
        if data.get("screenshot"):
            self.timeline.show_screenshot(data.get("screenshot"))

    def _toggle_pause(self):
        if self._paused:
            self.agent.resume()
            self._paused = False
            self.timeline.set_status("继续执行", "running")
        else:
            self.agent.pause()
            self._paused = True
            self.timeline.set_status("已暂停", "waiting")

    def _cancel(self):
        try:
            self.agent.cancel()
            self.timeline.set_status("正在取消", "cancelled")
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass

    def _rollback(self):
        if not self._backups:
            QMessageBox.information(self, "撤销", "没有可撤销的修改")
            return
        r = self.agent.rollback_all(self._backups)
        self._backups = []
        self.timeline.set_status("已撤销所有修改", "done")
        self.timeline.append_detail("回滚结果", "已恢复：%s" % (r.get("restored") or []))
        self.rollback_btn.setEnabled(False)

    def _on_prepared(self, result):
        self.run_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        if not isinstance(result, dict) or not result.get("ok"):
            msg = (result or {}).get("error", "准备失败")
            self.output.appendPlainText("[失败] " + str(msg))
            return
        patch = result.get("patch") or {}
        self.output.appendPlainText(
            "已生成 patch，相关文件：%s" %
            ", ".join(result.get("context_files") or []))
        try:
            dlg = DiffReviewDialog(self.root, patch, self)
            dlg.exec_()
        except Exception as e:
            self.output.appendPlainText("[审批失败] " + str(e)[:400])
            return
        if not dlg.accepted:
            self.output.appendPlainText("[已取消] 未应用修改")
            return
        manifest = (dlg.result or {}).get("backup_manifest")
        if manifest:
            # 累加而不是覆盖：界面上承诺"所有修改都可以一键撤销"，
            # 连续几轮修复后一键撤销要把每一轮都回滚掉。
            self._backups.append(manifest)
        self.rollback_btn.setEnabled(bool(self._backups))
        self.output.appendPlainText(
            "已应用文件：%s" % ", ".join(
                (dlg.result or {}).get("applied") or []))
        self._run_tests()

    def _run_tests(self):
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.timeline.set_status("正在运行测试与 lint", "running")
        self.output.appendPlainText(">>> 正在运行测试")
        self._test_worker = _TestWorker(self.agent)
        self._test_worker.done.connect(self._on_tests)
        self._test_worker.start()

    def _on_tests(self, result):
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        tests = (result or {}).get("tests") or {}
        lint = (result or {}).get("lint") or {}
        results = (tests.get("results") or []) + (lint.get("results") or [])
        for x in results:
            self.output.appendPlainText(
                "$ %s  (exit=%s)\n%s" % (
                    x.get("command", ""), x.get("exit_code", "?"),
                    x.get("output", "")[:3000]))
        failures = []
        for x in tests.get("results") or []:
            failures.extend(x.get("failures") or [])
        if failures:
            self.output.appendPlainText("失败定位：")
            for f in failures[:10]:
                self.output.appendPlainText(
                    "  %s%s :: %s %s" % (
                        f.get("file", ""),
                        (":" + str(f.get("line"))) if f.get("line") else "",
                        f.get("test", ""), f.get("message", "")))
        if result.get("ok"):
            self.output.appendPlainText("[完成] 测试通过")
            self.timeline.set_status("测试通过，任务完成", "done")
            self.timeline.set_progress(1.0)
            self.fix_btn.hide()
        else:
            self.output.appendPlainText(
                "[失败] 测试未通过；可点基于失败输出继续修复，"
                "本次 patch 仍可点「一键撤销」回滚")
            self.timeline.set_status("测试未通过", "failed")
            self.timeline.append_detail(
                "失败输出", "\n".join(
                    str(x.get("output", "")) for x in results)[:4000])
            self._last_error = "\n".join(
                str(x.get("output", "")) for x in results)
            self.fix_btn.show()

    def _running_workers(self):
        out = []
        for name in ("_worker", "_test_worker"):
            w = getattr(self, name, None)
            if w is not None and hasattr(w, "isRunning") and w.isRunning():
                out.append(w)
        return out

    def _maybe_finish_close(self):
        if self._close_pending and not self._running_workers():
            self._close_pending = False
            self.close()

    def closeEvent(self, event):
        workers = self._running_workers()
        if not workers:
            event.accept()
            return
        r = QMessageBox.question(
            self, "代码任务仍在运行",
            "关闭窗口会取消当前代码任务，是否继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            event.ignore()
            return
        try:
            self.agent.cancel()
        except Exception:  # 静默是故意的 - 关闭流程尽力取消
            pass
        for w in workers:
            try:
                w.wait(3000)
            except Exception:  # 静默是故意的 - 关闭流程尽力等待
                pass
        left = self._running_workers()
        if left:
            self._close_pending = True
            for w in left:
                try:
                    w.finished.connect(self._maybe_finish_close)
                except Exception:  # 静默是故意的 - 信号连接失败不影响隐藏窗口
                    pass
            self.hide()
            QMessageBox.information(
                self, "正在后台停止",
                "任务已请求取消，仍在等待底层命令退出。\n"
                "窗口已隐藏，线程安全退出后会自动关闭。")
            event.ignore()
            return
        event.accept()

