# -*- coding: utf-8 -*-
"""统一任务中心：计划、步骤、确认、结果与下一步。

所有任务入口（侧栏任务、输入框任务模式、聊天转为任务、命令面板
开始任务、聊天结果卡片）最终都打开这个页面。
"""
import html

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QMessageBox, QSplitter, QWidget,
    QFrame)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

from gui.feedback_states import make_action_links


class _TaskBridge(QObject):
    changed = pyqtSignal()


class TaskPlanRelay(QObject):
    """后台拆步的线程边界：工作线程只 emit，槽在 GUI 线程里执行。

    拆步要同步调用模型（几秒到几十秒），必须在后台线程做，否则整个窗口
    会假死。`rt.plan_async` 的完成回调在工作线程里跑，这里用信号把它拉回
    主线程，任务中心和主窗口共用同一个实现。
    """

    planned = pyqtSignal(str, bool)

    def __init__(self, rt, on_done, parent=None):
        super().__init__(parent)
        self.rt = rt
        self.planned.connect(on_done)

    def start(self, task_id):
        """开始后台拆步（重复调用同一个任务会被运行时合并成一次）。"""
        if not task_id:
            return
        self.rt.plan_async(task_id, self.planned.emit)


class TaskCenterDialog(QDialog):
    def __init__(self, trunk, parent=None, task_id=None, goal=None,
                 auto_start=False, auto_plan=False):
        super().__init__(parent)
        self.trunk = trunk
        self.rt = trunk.get_task_runtime()
        self.setWindowTitle(" 任务中心")
        self.resize(940, 680)
        self._current = task_id
        self._initial_goal = str(goal or "")
        self._auto_start = bool(auto_start)
        self._auto_plan = bool(auto_plan)
        self._guide_action = ""
        self._planning = set()
        self._pending_start = set()
        self._build()
        # 事件驱动：运行时只发有变化信号，不再每秒轮询整张表。
        self._bridge = _TaskBridge(self)
        self._bridge.changed.connect(self._schedule_refresh)
        self._on_rt_event = lambda *a: self._bridge.changed.emit()
        self.rt.subscribe(self._on_rt_event)
        self._relay = TaskPlanRelay(self.rt, self._on_planned, self)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._refresh)
        self._dirty = False
        self._refresh()
        if self._initial_goal:
            self.goal.setText(self._initial_goal)
            if self._auto_start:
                QTimer.singleShot(0, self._create_and_start)
        elif task_id and self._auto_plan:
            # 聊天 [任务] 模式：任务已建好，这里只负责拆步 + 自动开始。
            QTimer.singleShot(0, lambda: self._plan_async(task_id, True))

    def done(self, result):
        """关闭（含 Esc）时注销订阅，否则运行时会把信号发给已销毁的对话框。"""
        try:
            self.rt.unsubscribe(self._on_rt_event)
        except Exception as e:  # 静默是故意的 - 旧运行时没有 unsubscribe
            _x6_swallowed(__name__, e, "unsubscribe task events")
        super().done(result)

    def _build(self):
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("输入目标，例如：整理项目里的重复记忆")
        top.addWidget(self.goal, 1)
        new_btn = QPushButton("新建任务")
        new_btn.clicked.connect(self._create)
        self.new_btn = new_btn
        top.addWidget(new_btn)
        lay.addLayout(top)

        # 失败 / 权限 / 超时后的唯一下一步
        self.guide_box = QFrame()
        self.guide_box.setStyleSheet(
            "QFrame{background:#f0f7ff;border:1px solid #d6e8ff;"
            "border-radius:10px;}")
        gl = QHBoxLayout(self.guide_box)
        gl.setContentsMargins(10, 8, 10, 8)
        self.guide_label = QLabel("")
        self.guide_label.setWordWrap(True)
        self.guide_label.setStyleSheet("color:#1976d2;font-size:12px;")
        gl.addWidget(self.guide_label, 1)
        self.guide_btn = QLabel()
        self.guide_btn.setTextFormat(Qt.RichText)
        self.guide_btn.setOpenExternalLinks(False)
        self.guide_btn.linkActivated.connect(lambda _l: self._run_guide_action())
        self._set_guide_link("下一步")
        gl.addWidget(self.guide_btn)
        self.guide_box.hide()
        lay.addWidget(self.guide_box)

        split = QSplitter()
        self.list = QListWidget()
        self.list.itemClicked.connect(self._select)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("任务"))
        ll.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        rl.addWidget(self.detail, 1)
        btns = QHBoxLayout()
        self.action_buttons = {}
        acts = [("开始", self._start), ("暂停", self._pause),
                ("恢复", self._resume), ("取消", self._cancel),
                ("重试失败步骤", self._retry),
                ("增加预算并继续", self._increase_budget),
                ("刷新", self._refresh)]
        # 动作行统一做成链接：任务中心的按钮位只留给「新建任务」和「下一步」，
        # 七个并排按钮在窄窗口里会被挤成豆腐块（按钮预算也只许降）。
        link = make_action_links(acts, separator="  ")
        for text, _fn in acts:
            self.action_buttons[text] = link
        btns.addWidget(link)
        btns.addStretch(1)
        rl.addLayout(btns)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([260, 680])
        lay.addWidget(split, 1)

    def _schedule_refresh(self):
        self._dirty = True
        if not self._debounce.isActive():
            self._debounce.start(80)

    def _refresh(self):
        self._dirty = False
        tasks = self.rt.list_tasks()
        sel = self._current
        self.list.clear()
        for t in tasks:
            item = QListWidgetItem("[%s] %s" % (
                t.get("status"), t.get("goal", "")))
            item.setData(256, t.get("id"))
            self.list.addItem(item)
            if t.get("id") == sel:
                self.list.setCurrentItem(item)
        if not tasks:
            self.detail.setPlainText(
                "还没有任务。\n\n输入目标后点「新建任务」，"
                "计划、步骤、确认和结果都会在这里显示。")
            self._update_guidance(None)
            return
        if sel:
            self._show(sel)
        elif tasks:
            self._current = tasks[0].get("id")
            self.list.setCurrentRow(0)
            self._show(self._current)

    def _create(self):
        goal = self.goal.text().strip()
        if not goal:
            QMessageBox.information(self, "任务中心", "请输入目标")
            return
        t = self.rt.create(goal)
        self._current = t["id"]
        self.goal.clear()
        self._mark_first_task()
        self._show(t["id"])
        self._plan_async(t["id"])

    def _create_and_start(self):
        goal = self.goal.text().strip()
        if not goal:
            return
        t = self.rt.create(goal)
        self._current = t["id"]
        self.goal.clear()
        self._mark_first_task()
        self._refresh()
        self._plan_async(t["id"], then_start=True)

    def _mark_first_task(self):
        try:
            p = self.parent()
            if p and hasattr(p, "_mark_guide_event"):
                p._mark_guide_event("first_task")
        except Exception as e:  # 静默是故意的 - 父窗口没有引导模块也能用
            _x6_swallowed(__name__, e, "mark first task")

    def _plan_async(self, task_id, then_start=False):
        """后台拆步（模型调用不在 GUI 线程），拆完按需自动开始。"""
        if not task_id or task_id in self._planning:
            return
        t = self.rt.get_task(task_id)
        if not t:
            return
        if t.get("steps"):
            # 已经有计划：只补启动，不再重复拆步。
            if then_start:
                self._current = task_id
                self._start_current()
            return
        self._planning.add(task_id)
        if then_start:
            self._pending_start.add(task_id)
        self._current = task_id
        self.new_btn.setEnabled(False)
        self._refresh()
        self._relay.start(task_id)

    def _on_planned(self, task_id, ok):
        self._planning.discard(task_id)
        self.new_btn.setEnabled(True)
        if not ok:
            self._pending_start.discard(task_id)
            QMessageBox.warning(
                self, "任务中心", "计划拆解失败：模型没有给出步骤，可以重试")
            self._refresh()
            return
        self._refresh()
        if task_id in self._pending_start:
            self._pending_start.discard(task_id)
            self._current = task_id
            self._start_current()

    def _start_current(self):
        """启动当前任务；没有步骤就先去后台拆步。"""
        if not self._current:
            return
        t = self.rt.get_task(self._current)
        if not t:
            return
        if not t.get("steps"):
            self._plan_async(self._current, then_start=True)
            return
        r = self.rt.start(self._current)
        if not r.get("ok"):
            QMessageBox.warning(self, "任务中心", str(r.get("错误", "启动失败")))
        else:
            self._watch_in_parent()
        self._refresh()

    def _select(self, item):
        self._current = item.data(256)
        self._show(self._current)

    def show_task(self, task_id):
        """切到指定任务（主窗口复用同一个任务中心时调用）。

        任务中心改为单窗口后，聊天卡片 / 活动中心再点「查看任务」
        不会新开一个窗口，而是把已有的这个切到对应任务。
        """
        if not task_id:
            return
        self._current = task_id
        self._refresh()
        self._show(task_id)
        self.raise_()
        self.activateWindow()

    def _show(self, task_id):
        t = self.rt.get_task(task_id)
        if not t:
            return
        self._current = task_id
        lines = ["目标：%s" % t.get("goal", ""),
                 "状态：%s" % t.get("status", ""),
                 "任务ID：%s" % t.get("id", ""),
                 "耗时预算：%ss" % t.get("budget", {}).get("max_seconds", ""),
                 "", "步骤："]
        if task_id in self._planning:
            lines.insert(2, "正在后台拆解计划…界面可以继续操作，完成后会自动开始。")
        for s in t.get("steps", []):
            icon = {"done": "", "running": "", "failed": "",
                    "paused": "", "pending": ""}.get(
                        s.get("status"), "")
            lines.append("%s %s  [%s] %s" % (
                icon, s.get("id"), s.get("status"), s.get("title", "")))
            if s.get("error"):
                lines.append("   错误: " + str(s.get("error"))[:300])
            if s.get("result_preview"):
                lines.append("   结果: " + str(s.get("result_preview"))[:500])
        if t.get("final"):
            lines += ["", "最终结果：", str(t["final"])[:4000]]
        if t.get("error"):
            lines += ["", "错误：", str(t["error"])[:1000]]
        self.detail.setPlainText("\n".join(lines))
        self._update_guidance(t)

    def _update_guidance(self, task):
        if not task or task.get("status") not in (
                "failed", "cancelled", "paused", "completed"):
            self.guide_box.hide()
            self._guide_action = ""
            return
        if task.get("status") == "completed":
            self.guide_box.hide()
            return
        try:
            from gui.guidance import next_step_for_error
            guide = next_step_for_error(task.get("error", "") or
                                        task.get("status", ""))
        except Exception:  # 静默是故意的
            guide = {"title": "任务未完成", "message": "查看错误后重试。",
                     "action": "retry_failed_step",
                     "action_label": "重试失败步骤"}
        self._guide_action = guide.get("action", "")
        self.guide_label.setText(
            "<b>%s</b>　%s" % (guide.get("title", ""),
                               guide.get("message", "")))
        self._set_guide_link(guide.get("action_label", "下一步"))
        self.guide_box.show()

    def _set_guide_link(self, text):
        self.guide_btn.setText(
            '<a href="go" style="color:#1976d2;font-weight:600;">%s</a>'
            % html.escape(text or "下一步"))

    def _run_guide_action(self):
        action = self._guide_action
        p = self.parent()
        try:
            if action == "retry_failed_step":
                self._retry()
            elif action == "increase_task_budget":
                self._increase_budget()
            elif action == "open_plugin_market" and p is not None:
                p.plugin_dialog()
            elif action in ("open_security_center",
                            "open_security_network_events") and p is not None:
                p.security_center_dialog()
            elif action == "open_model_settings" and p is not None:
                p.set_dialog()
            else:
                self._retry()
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "下一步", str(e)[:120])

    def _watch_in_parent(self):
        try:
            p = self.parent()
            if p is not None and hasattr(p, "_watch_task_result"):
                p._watch_task_result(self._current)
        except Exception:  # 静默是故意的
            pass

    def _start(self):
        self._start_current()

    def _pause(self):
        if self._current:
            self.rt.pause(self._current)
            self._refresh()

    def _resume(self):
        if self._current:
            r = self.rt.resume(self._current)
            if not r.get("ok"):
                QMessageBox.warning(self, "任务中心", str(r.get("错误")))
            else:
                self._watch_in_parent()
            self._refresh()

    def _cancel(self):
        if self._current:
            self.rt.cancel(self._current)
            self._refresh()

    def _retry(self):
        if not self._current:
            return
        t = self.rt.get_task(self._current)
        target = next((s for s in t.get("steps", [])
                       if s.get("status") == "failed"), None)
        if target:
            self.rt.retry_step(self._current, target["id"])
            self._watch_in_parent()
            self._refresh()
        else:
            r = self.rt.resume(self._current)
            if not r.get("ok"):
                QMessageBox.information(self, "任务中心", "没有失败步骤")
            else:
                self._watch_in_parent()
            self._refresh()

    def _increase_budget(self):
        if not self._current:
            return
        try:
            if hasattr(self.rt, "increase_budget"):
                self.rt.increase_budget(
                    self._current, seconds=120, steps=4, tokens=5000)
            t = self.rt.get_task(self._current)
            for s in t.get("steps", []):
                if s.get("status") == "failed":
                    s["status"] = "pending"
                    s["error"] = ""
            t["status"] = "pending"
            t["error"] = ""
            self.rt._save(t)
            self.rt.start(self._current)
            self._watch_in_parent()
            self._refresh()
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "增加预算", str(e)[:120])

