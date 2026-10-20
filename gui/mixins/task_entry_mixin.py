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
    def open_task_center(self, task_id=None, goal=None, auto_start=False):
        """所有任务入口最终都到这里：侧栏、输入框、聊天卡片、命令面板。"""
        try:
            from gui.task_center_dialog import TaskCenterDialog
            d = TaskCenterDialog(self.trunk, self, task_id=task_id,
                                 goal=goal, auto_start=auto_start)
            if not hasattr(self, "_task_centers"):
                self._task_centers = []
            self._task_centers.append(d)
            d.show()
            d.raise_()
            return d
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "任务中心", "打不开：" + str(e)[:120])
            return None

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
            rt.plan(task["id"])
            self.chat.append_user(text)
            self.chat.append(
                "<div style='color:#1976d2'> 已进入任务模式：正在拆解计划，"
                "执行过程会显示在任务中心。</div>")
            try:
                self.account.save_line("u", text)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            self.input.clear()
            self._mark_guide_event("first_task")
            r = rt.start(task["id"])
            if not r.get("ok"):
                self.chat.append_guidance_card(
                    "任务启动失败", str(r.get("错误", "未知错误")),
                    "guidance://retry_failed_step", "重试失败步骤")
            self._watch_task_result(task["id"])
            self.open_task_center(task_id=task["id"])
        except Exception as e:  # 静默是故意的
            QMessageBox.warning(self, "任务模式", "启动失败：" + str(e)[:120])

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
            self.chat.append_task_result_card(
                tid, status, "", err, action, guide.get("action_label"))
            self.chat.append_guidance_card(
                guide.get("title"), guide.get("message"),
                "guidance://" + guide.get("action"), guide.get("action_label"))
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
