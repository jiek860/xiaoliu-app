# -*- coding: utf-8 -*-
"""主窗口任务入口、任务轮询、结果卡片和预算。"""
from __future__ import annotations

import time
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TaskEntryMixin:
    def open_task_center(self, task_id=None, goal=None, auto_start=False,
                         auto_plan=False):
        """所有任务入口最终都到这里：侧栏、输入框、聊天卡片、命令面板。

        单窗口：第一次真建任务中心，后面无论点多少次都只把已有的
        前置/切到对应任务，不再叠第二个窗口。
        """
        try:
            from gui.task_center_dialog import TaskCenterDialog

            def _focus(w):
                if task_id:
                    w.show_task(task_id)
                elif goal:
                    try:
                        w.goal.setText(str(goal))
                    except Exception as e:  # 静默是故意的 - 只影响输入框预填
                        _x6_swallowed(__name__, e, "prefill task goal")

            return self._singleton_window(
                "task_center",
                lambda: TaskCenterDialog(self.trunk, self, task_id=task_id,
                                         goal=goal, auto_start=auto_start,
                                         auto_plan=auto_plan),
                focus=_focus)
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "任务中心", "打不开：" + str(e)[:120])
            return None

    @staticmethod
    def _dialog_alive(widget):
        """已关闭/已销毁的任务中心不再留在列表里（否则列表只增不减）。"""
        try:
            return bool(widget.isVisible())
        except Exception:  # 静默是故意的 - 底层 C++ 对象已销毁
            return False

    def task_center_dialog(self):
        # 兼容旧命令面板入口
        return self.open_task_center()

    def start_task(self, goal=None, auto_start=False):
        if goal:
            self._mark_guide_event("first_task")
        return self.open_task_center(goal=goal, auto_start=auto_start)

    def scheduled_tasks_dialog(self):
        """定时任务也进入统一任务中心；调度本身仍由 scheduler 在后台运行。"""
        return self.open_task_center()

    def _send_task(self, text):
        """输入框 [任务] 模式：直接进入任务运行时，不再走聊天链路。"""
        text = str(text or "").strip()
        if not text:
            return
        try:
            rt = self.trunk.get_task_runtime()
            task = rt.create(text)
            self.chat.append_user(text)
            self.chat.append(
                "<div style='color:#1976d2'> 已进入任务模式：正在后台拆解计划，"
                "界面可以继续操作；拆完会自动开始，进度在任务中心。</div>")
            try:
                self.account.save_line("u", text)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            self.input.clear()
            self._clear_draft()
            self._mark_guide_event("first_task")
            # 拆步要调模型，放后台线程；完成后自动启动并盯结果。
            self._plan_task_async(task["id"])
            self.open_task_center(task_id=task["id"])
            self._watch_task_result(task["id"])
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "任务模式", "启动失败：" + str(e)[:120])

    def _plan_task_async(self, task_id):
        """后台拆步（聊天 [任务] 模式用），不阻塞界面。"""
        from gui.task_center_dialog import TaskPlanRelay
        relay = getattr(self, "_task_plan_relay", None)
        if relay is None or relay.rt is not self.trunk.get_task_runtime():
            relay = TaskPlanRelay(self.trunk.get_task_runtime(),
                                  self._on_task_planned, self)
            self._task_plan_relay = relay
        relay.start(task_id)

    def _on_task_planned(self, task_id, ok):
        if not ok:
            self.chat.append_guidance_card(
                "任务拆解失败", "模型没有给出可执行的步骤，换一种说法再试一次。",
                "retry://" + task_id, "重试这个任务")
            return
        try:
            r = self.trunk.get_task_runtime().start(task_id)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "start planned task")
            r = {"ok": False, "错误": str(e)[:120]}
        if not r.get("ok"):
            self.chat.append_guidance_card(
                "任务启动失败", str(r.get("错误", "未知错误")),
                "guidance://retry_failed_step", "重试失败步骤")
        self._watch_task_result(task_id)

    def _watch_task_result(self, task_id, interval_ms=1000, max_seconds=900):
        if not task_id:
            return
        if not hasattr(self, "_task_watchers"):
            self._task_watchers = {}
        if task_id in self._task_watchers:
            return
        timer = QTimer(self)
        timer.setInterval(int(interval_ms))
        started = time.time()
        self._task_watchers[task_id] = timer

        def tick():
            if time.time() - started > max_seconds:
                timer.stop()
                self._task_watchers.pop(task_id, None)
                return
            try:
                task = self.trunk.get_task_runtime().get_task(task_id)
            except Exception:  # 静默是故意的
                timer.stop()
                self._task_watchers.pop(task_id, None)
                return
            status = (task or {}).get("status", "")
            if status in ("completed", "failed", "cancelled"):
                timer.stop()
                self._task_watchers.pop(task_id, None)
                self._on_task_card(task)
        timer.timeout.connect(tick)
        timer.start()
        tick()

    def _on_task_card(self, task):
        if not task:
            return
        tid = task.get("id", "")
        shown = getattr(self, "_task_cards_shown", set())
        if tid and tid in shown:
            return
        if tid:
            shown.add(tid)
            self._task_cards_shown = shown
        status = task.get("status", "")
        if status == "completed":
            self.chat.append_task_result_card(
                tid, status, task.get("final", ""), "", "task://" + tid,
                "查看任务")
        else:
            err = task.get("error", "") or status
            guide = self.guidance.for_error(err)
            action = "task-budget://" + tid \
                if guide.get("action") == "increase_task_budget" \
                else "retry://" + tid
            # 一张卡 + 一个下一步：把引导话术并进结果卡，不再额外刷一张卡。
            body = ("%s %s" % (guide.get("message") or "", err)).strip()
            self.chat.append_task_result_card(
                tid, status, body, err, action, guide.get("action_label"))
        self._update_empty_state()

    def _handle_last_task_result(self):
        info = getattr(self.trunk, "last_task_result", None)
        if not isinstance(info, dict) or not info.get("task_id"):
            return
        self._mark_guide_event("first_task")
        tid = info["task_id"]
        try:
            task = self.trunk.get_task_runtime().get_task(tid)
        except Exception:  # 静默是故意的
            task = None
        if task:
            if task.get("status") in ("completed", "failed", "cancelled"):
                self._on_task_card(task)
            else:
                self._watch_task_result(tid)
        else:
            if info.get("ok"):
                self.chat.append_task_result_card(
                    tid, "completed", str(info.get("结果", "")),
                    "", "task://" + tid, "查看任务")
            else:
                guide = self.guidance.for_error(info.get("错误", ""))
                self.chat.append_task_result_card(
                    tid, "failed", "", str(info.get("错误", "")),
                    "retry://" + tid, guide.get("action_label"))

    def _retry_task(self, task_id):
        try:
            rt = self.trunk.get_task_runtime()
            task = rt.get_task(task_id)
            if not task:
                QMessageBox.information(self, "任务", "任务不存在")
                return
            failed = next((s for s in task.get("steps", [])
                           if s.get("status") == "failed"), None)
            if failed:
                rt.retry_step(task_id, failed["id"])
            else:
                rt.resume(task_id)
            self.open_task_center(task_id=task_id)
            self._watch_task_result(task_id)
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "重试任务", str(e)[:120])

    def _increase_task_budget(self, task_id):
        try:
            rt = self.trunk.get_task_runtime()
            if hasattr(rt, "increase_budget"):
                rt.increase_budget(task_id, seconds=120, steps=4, tokens=5000)
            task = rt.get_task(task_id)
            for s in task.get("steps", []):
                if s.get("status") == "failed":
                    s["status"] = "pending"
                    s["error"] = ""
            task["status"] = "pending"
            task["error"] = ""
            rt._save(task)
            rt.start(task_id)
            self.open_task_center(task_id=task_id)
            self._watch_task_result(task_id)
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "继续任务", str(e)[:120])
