# -*- coding: utf-8 -*-
"""统一任务中心：计划、步骤、确认、结果与下一步。

所有任务入口（侧栏任务、输入框任务模式、聊天转为任务、命令面板
开始任务、聊天结果卡片）最终都打开这个页面。
"""
import html

from PyQt5.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextBrowser, QMessageBox, QSplitter,
    QWidget, QFrame)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

from gui.feedback_states import make_action_links

# 渲染/引导拆到 gui/task_center_view.py（本文件到 600 行上限）。
from gui.task_center_view import TaskCenterViewMixin


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


class TaskCenterDialog(TaskCenterViewMixin, QDialog):
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
        self.detail = QTextBrowser()
        # 失败步骤里的「重试 / 换方案 / 补充说明 / 失败经过」都是富文本链接，
        # 不占按钮位；点击后在本窗口内处理，不再单独弹窗。
        self.detail.setOpenLinks(False)
        self.detail.setOpenExternalLinks(False)
        self.detail.anchorClicked.connect(self._on_anchor)
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
            self.detail.setHtml(self._empty_html())
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
        parts = [
            "<div style='font-size:13px;color:#344054;'>目标：<b>%s</b></div>"
            % html.escape(str(t.get("goal", ""))),
            "<div style='font-size:12px;color:#667085;margin-top:2px;'>"
            "状态：%s　任务ID：%s　耗时预算：%ss</div>"
            % (html.escape(str(t.get("status", ""))),
               html.escape(str(t.get("id", "")), quote=True),
               html.escape(str(t.get("budget", {}).get("max_seconds", ""))))
        ]
        if task_id in self._planning:
            parts.append(
                "<div style='color:#175cd3;font-size:12px;'>"
                "正在后台拆解计划…界面可以继续操作，完成后会自动开始。</div>")
        parts.append("<div style='margin-top:10px;font-weight:700;'>步骤：</div>")
        steps = t.get("steps") or []
        if not steps:
            parts.append(
                "<div style='color:#667085;font-size:12px;'>"
                "还没有计划，点击「开始」会自动拆解。</div>")
        for s in steps:
            parts.append(self._step_html(s))
        if t.get("final"):
            parts.append(
                "<div style='margin-top:10px;font-weight:700;'>最终结果：</div>"
                "<div style='font-size:12px;color:#344054;'>%s</div>"
                % html.escape(str(t["final"])[:4000]).replace("\n", "<br>"))
        if t.get("error"):
            parts.append(
                "<div style='margin-top:8px;color:#b42318;'>"
                "<b>任务失败原因：</b>%s</div>"
                % html.escape(str(t["error"])[:1000]))
        parts.append(self._schedule_html())
        self.detail.setHtml("".join(parts))
        self._update_guidance(t)

    def _on_anchor(self, url):
        """富文本链接统一入口：步骤动作 + 定时任务管理。"""
        href = url.toString() if hasattr(url, "toString") else str(url)
        scheme, _, rest = href.partition("://")
        if scheme == "step-retry":
            self._retry_step(rest)
        elif scheme == "step-replan":
            self._replan()
        elif scheme == "step-ask":
            self._ask_user()
        elif scheme == "step-trace":
            self.detail.scrollToAnchor("trace-" + rest)
        elif scheme == "schedule-stop":
            self._set_scheduler(False)
        elif scheme == "schedule-start":
            self._set_scheduler(True)
        elif scheme == "schedule-interval":
            self._change_schedule_interval()
        elif scheme == "schedule-run":
            self._run_scheduled(rest)

    def _retry_step(self, step_id):
        if not self._current or not step_id:
            return
        if not hasattr(self.rt, "retry_step"):
            self._retry()
            return
        try:
            r = self.rt.retry_step(self._current, step_id)
        except Exception as e:
            QMessageBox.warning(self, "重试步骤", str(e)[:120])
            return
        if isinstance(r, dict) and not r.get("ok"):
            QMessageBox.information(
                self, "任务中心", str(r.get("错误", "重试失败")))
            return
        self._watch_in_parent()
        self._refresh()

    def _replan(self):
        if not self._current:
            return
        try:
            r = self.rt.replan(self._current) \
                if hasattr(self.rt, "replan") else {"ok": True}
        except Exception as e:
            QMessageBox.warning(self, "换个做法", str(e)[:120])
            return
        if not r.get("ok"):
            QMessageBox.warning(
                self, "换个做法", str(r.get("错误", "无法重新拆解")))
            return
        self._plan_async(self._current, then_start=True)

    def _ask_user(self):
        t = self.rt.get_task(self._current) if self._current else None
        goal = str((t or {}).get("goal", ""))
        if goal:
            self.goal.setText(goal)
        self.goal.setFocus()
        self.goal.selectAll()
        self._guide_action = "replan"
        self.guide_label.setText(
            "<b>补充目标信息</b>　在目标框里说清范围/约束，再点「重新拆解」。")
        self._set_guide_link("重新拆解")
        self.guide_box.show()

    def _set_scheduler(self, enable):
        sc = self._module("scheduler")
        if sc is None:
            QMessageBox.information(self, "定时任务", "没有安装调度模块")
            return
        try:
            sc.start() if enable else sc.stop()
        except Exception as e:
            QMessageBox.warning(self, "定时任务", str(e)[:120])
            return
        self._refresh()

    def _change_schedule_interval(self):
        sc = self._module("scheduler")
        if sc is None:
            QMessageBox.information(self, "定时任务", "没有安装调度模块")
            return
        engine = self._module("rules_engine")
        try:
            current = int(engine.get("定时.工作流间隔秒", 60)) \
                if engine is not None and hasattr(engine, "get") else 60
        except Exception:  # 静默是故意的 - 读不到就用默认值
            current = 60
        from PyQt5.QtWidgets import QInputDialog
        value, ok = QInputDialog.getInt(
            self, "定时任务", "工作流检查间隔（秒）", current, 10, 3600, 10)
        if not ok:
            return
        try:
            if engine is not None and hasattr(engine, "set"):
                engine.set("定时.工作流间隔秒", int(value))
            else:
                QMessageBox.information(
                    self, "定时任务", "当前环境没有规则引擎，间隔修改不会生效")
                return
        except Exception as e:
            QMessageBox.warning(self, "定时任务", str(e)[:120])
            return
        self._refresh()

    def _run_scheduled(self, name):
        runner = self._module("workflow_runner")
        if runner is None or not name:
            return
        try:
            if hasattr(runner, "start_async"):
                runner.start_async(name)
            else:
                runner.run(name)
        except Exception as e:
            QMessageBox.warning(self, "定时任务", "运行失败：" + str(e)[:100])
            return
        self._refresh()

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

