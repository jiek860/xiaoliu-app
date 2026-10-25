# -*- coding: utf-8 -*-
"""小6 工作台：编辑器 + AI Agent 同屏（无页签）。

为什么这样设计
--------------
原来有三个独立窗口：代码编辑器 / Agent 旅程 / AI 代码 Agent。
用户改完 AI 生成的代码想手动微调，必须关掉一个再开另一个 —— 文件、目录、
选中片段全丢。而且三者重复实现了线程、diff 审批、时间线。

本工作台把三者放在**同一屏**：

    +------------------+------------------------------------+
    | 文件树            | 编辑器（多标签 = 多个文件，非功能页签） |
    |                  +------------------------------------+
    |                  | AI 面板（可折叠 / 可弹出为独立窗口）   |
    +------------------+------------------------------------+
    | 运行输出                                              |
    +-------------------------------------------------------+

* 没有"功能页签"：不存在"编辑器页/旅程页/Agent页"的切换
* 编辑器里的标签页只是**多个文件**，跟原来一样
* AI 面板与编辑器共享同一份"当前打开文件"上下文
* [弹出] 可把 AI 面板独立出去（双屏时贴到副屏），再点收回

兼容性：旧入口 open_code_editor / agent_journey_dialog / code_agent_dialog
全部改为打开本工作台并定位到对应区域，菜单文字与位置不变。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QMessageBox,
                             QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                             QVBoxLayout, QWidget)

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
            result = self.orchestrator.run(
                goal, resume_state=resume_state or {}, checkpoint_cb=checkpoint)
            if self.queue and self.current_job_id:
                self.queue.mark_done(self.current_job_id, result)
                self._refresh_queue()
            self._on_done(result)
        except Exception as e:  # 静默是故意的 - 出错要显示给用户而不是崩
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


class WorkbenchWindow(QMainWindow):
    """统一工作台：编辑器 + AI 面板同屏，无功能页签。"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.root = os.path.abspath(
            getattr(trunk, "base", ".") or os.getcwd())
        self._ai_popup = None
        self._ai_placeholder = None
        self._ai_shown = True          # AI 面板默认展开
        self._editor = None
        self.setWindowTitle("🧰 小6 工作台")
        self.resize(1440, 900)
        self._build()

    # ---------------------------------------------------------- 构建
    def _build(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 顶部工具条：唯一的"打开 Agent"入口就用这里的 AI 面板，无需按钮切换
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        self.title = QLabel("🧰 工作台")
        self.title.setStyleSheet("font-weight:700;font-size:13px;")
        bar.addWidget(self.title)
        self.root_label = QLabel(os.path.basename(self.root) or self.root)
        self.root_label.setStyleSheet("color:#667085;font-size:11px;")
        self.root_label.setToolTip(self.root)
        bar.addWidget(self.root_label)
        bar.addStretch(1)
        hint = QLabel("Ctrl+J 收起 AI · F11 全屏 · 拖动分隔条调整比例")
        hint.setStyleSheet("color:#98a2b3;font-size:11px;")
        bar.addWidget(hint)
        # 收起/展开不占按钮：AI 面板是 splitter 的一部分，直接拖动分隔条即可；
        # 也支持 Ctrl+J 快捷键（见 _install_shortcuts）。
        self.collapse_btn = None
        v.addLayout(bar)

        # 主体：左文件树 | 右上编辑器 / 右下 AI
        self.splitter = QSplitter(Qt.Horizontal)
        self.editor_host = self._make_editor_host()
        self.splitter.addWidget(self.editor_host)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.vertical = QSplitter(Qt.Vertical)
        self.vertical.addWidget(self._make_editor_slot())
        self.ai_dock = AgentDock(self)
        self.vertical.addWidget(self.ai_dock)
        self.vertical.setSizes([620, 240])
        rv.addWidget(self.vertical, 1)
        self.splitter.addWidget(right)
        self.splitter.setSizes([280, 1160])
        v.addWidget(self.splitter, 1)
        self.setCentralWidget(central)
        self._install_shortcuts()

    def _install_shortcuts(self):
        """用快捷键替代按钮，减少界面控件数量。

        Ctrl+J  收起 / 展开 AI 面板
        F11     全屏切换
        """
        try:
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWidgets import QShortcut
            QShortcut(QKeySequence("Ctrl+J"), self, self.toggle_ai)
            QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        except Exception as e:  # 静默是故意的 - 快捷键装不上不影响使用
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _make_editor_host(self):
        """左：文件树（复用编辑器的实现）。"""
        return QWidget()

    def _make_editor_slot(self):
        """右上：嵌入 CodeEditorDialog 的编辑区。

        复用 CodeEditorDialog 而不是重写 —— 语法高亮、jedi 补全、
        多文件标签、运行输出都已经在里面验证过。
        """
        slot = QWidget()
        lay = QVBoxLayout(slot)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            from gui.code_editor_dialog import CodeEditorDialog
            self._editor = CodeEditorDialog(self.trunk, self)
            # 把它拆成"普通 QWidget"，这样能嵌进布局而不是独立窗口
            widget = self._editor.centralWidget()
            if widget is not None:
                lay.addWidget(widget)
                self._editor.setCentralWidget(QWidget())   # 解绑，避免重复父级
            else:
                lay.addWidget(self._editor)
        except Exception as e:  # 静默是故意的 - 编辑器坏了也不能让工作台打不开
            _x6_swallowed(__name__, e, "best-effort fallback")
            lay.addWidget(QLabel("编辑器加载失败：%s" % str(e)[:200]))
        return slot

    # ---------------------------------------------------------- 对外
    def editor_open_files(self):
        """当前编辑器里打开的所有文件路径（供 AI 参考）。"""
        out = []
        try:
            tabs = getattr(self._editor, "tabs", None)
            if tabs is None:
                return out
            for i in range(tabs.count()):
                w = tabs.widget(i)
                path = getattr(w, "filepath", "") or ""
                if path:
                    out.append(path)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return out

    def open_path(self, path):
        """供外部（菜单/聊天/AI）打开某个文件。"""
        try:
            if self._editor is not None and hasattr(self._editor, "open_path"):
                self._editor.open_path(path)
                return True
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return False

    def show_diff_preview(self, root, patch, on_apply=None, on_undo=None):
        """编辑器内联 diff 预览（供 AI 面板 / 聊天调用）。"""
        try:
            if self._editor is not None and hasattr(self._editor, "show_diff_preview"):
                return self._editor.show_diff_preview(
                    root, patch, on_apply=on_apply, on_undo=on_undo)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show workbench diff preview")
        return None

    def mark_diff_applied(self, manifest=""):
        try:
            if self._editor is not None and hasattr(self._editor, "mark_diff_applied"):
                self._editor.mark_diff_applied(manifest)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "mark diff applied")

    def reload_editor_path(self, path):
        """Agent 落盘后刷新对应的打开 tab。"""
        root = getattr(self, "root", None) or "."
        if path and not os.path.isabs(str(path)):
            path = os.path.join(root, str(path))
        try:
            if self._editor is not None and hasattr(self._editor, "reload_path"):
                self._editor.reload_path(path)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "reload editor path")

    def set_goal(self, text):
        try:
            self.ai_dock.goal.setPlainText(str(text or ""))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    # ---------------------------------------------------------- AI 面板
    def toggle_ai(self):
        """收起 / 展开 AI 面板。

        ⚠️ 不能用 isVisible() 判断当前状态：窗口还没 show() 时它恒为 False，
           会导致第一次点击"收起"变成"展开"。这里用显式状态位。
        """
        shown = getattr(self, "_ai_shown", True)
        shown = not shown
        self._ai_shown = shown
        self.ai_dock.setVisible(shown)

    def toggle_ai_popup(self):
        """把 AI 面板弹出为独立窗口（可拖到第二块屏幕），再点收回。

        实现要点：QSplitter 的 widget 不能直接 takeChildren，
        必须用 replaceWidget 换成占位控件，否则 splitter 布局会崩。
        """
        if self._ai_popup is not None:
            self._close_ai_popup()
            return
        try:
            placeholder = QWidget()
            self.vertical.replaceWidget(1, placeholder)
            self._ai_placeholder = placeholder
            win = QMainWindow(self)
            win.setWindowTitle("🤖 AI 面板 · 小6")
            win.resize(560, 460)
            win.setCentralWidget(self.ai_dock)
            win.show()
            self._ai_popup = win
            self.ai_dock.expand_btn.setText("⛶ 收回")
        except Exception as e:  # 静默是故意的 - 弹出失败就保持内嵌
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _close_ai_popup(self):
        """把 AI 面板收回工作台。"""
        try:
            win = self._ai_popup
            self._ai_popup = None
            if win is not None:
                win.setCentralWidget(QWidget())      # 先解绑，否则控件被带走
                win.close()
            placeholder = getattr(self, "_ai_placeholder", None)
            if placeholder is not None:
                self.vertical.replaceWidget(1, self.ai_dock)
                placeholder.deleteLater()
                self._ai_placeholder = None
            self.ai_dock.expand_btn.setText("⛶ 弹出")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        try:
            if self._ai_popup is not None:
                self._close_ai_popup()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        super().closeEvent(event)