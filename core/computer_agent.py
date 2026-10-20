# -*- coding: utf-8 -*-
"""电脑操控 Agent：Observe -> Ground -> Plan -> Act -> Verify -> Replan。

本次闭环补齐：
* 每一步都重新观察屏幕，并允许失败后重新规划；
* UIA / OCR / 多模态候选统一带 element_id + rect + confidence；
* 点击优先 UIA，其次元素 rect，最后真实坐标，不再依赖模型臆造坐标；
* 浏览器优先走 Playwright DOM；
* 动作级权限审计、暂停/取消/人工接管、文件操作回滚；
* 结构化事件流，可被 GUI 实时时间线消费。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from collections import OrderedDict

from core.action_schema import (
    ActionError, action_summary, make_action, requires_confirmation,
    validate_action,
)
from core.agent_harness import get_run_registry
from core.agent_permissions import authorize_agent_action
from core.visual_grounding import parse_uia_lines, ground, fuse_grounding


from core.computer_shared import AgentCancelled
from core.computer_perception import ComputerPerceptionMixin
from core.computer_planner import ComputerPlannerMixin
from core.gui_agent_quality import repair_strategy
from core.computer_executor import ComputerExecutorMixin
from core.computer_verifier import ComputerVerifierMixin

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class ComputerAgent(
    ComputerPerceptionMixin,
    ComputerPlannerMixin,
    ComputerExecutorMixin,
    ComputerVerifierMixin,
):
    def __init__(self, trunk, event_cb=None, max_steps=12):
        self.trunk = trunk
        self.controller = None
        self.registry = get_run_registry()
        self.event_cb = event_cb
        self.max_steps = max(1, int(max_steps or 12))
        self._cancel = None
        self._pause = None
        self._last_run_id = ""
        self._element_map = {}
        self._run_dir = ""
        self._rollback_items = []
        self._rollback_store = None
        self._approved_action_ids = set()
        self._ocr_cache = OrderedDict()

    def _ensure_events(self):
        import threading
        if self._cancel is None:
            self._cancel = threading.Event()
        if self._pause is None:
            self._pause = threading.Event()

    def cancel(self):
        self._ensure_events()
        self._cancel.set()

    def pause(self):
        self._ensure_events()
        self._pause.set()

    def resume(self):
        self._ensure_events()
        self._pause.clear()

    def is_paused(self):
        return bool(self._pause and self._pause.is_set())

    def _check_control(self):
        self._ensure_events()
        if self._cancel.is_set():
            raise AgentCancelled("任务已取消")
        while self._pause.is_set():
            if self._cancel.is_set():
                raise AgentCancelled("任务已取消")
            time.sleep(0.15)

    def _sleep(self, seconds):
        end = time.time() + max(0.0, float(seconds or 0))
        while time.time() < end:
            self._check_control()
            time.sleep(min(0.1, end - time.time()))

    def _emit(self, event, data=None):
        payload = {"event": str(event), "data": data or {},
                   "run_id": self._last_run_id, "time": time.time()}
        try:
            if callable(self.event_cb):
                self.event_cb(event, data or {})
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        if self._last_run_id:
            try:
                changes = {
                    "current_step": str((data or {}).get("step") or event),
                    "metadata": {"last_event": event,
                                 "detail": str(data or "")[:500]},
                }
                if isinstance((data or {}).get("progress"), (int, float)):
                    changes["progress"] = max(0.0, min(
                        1.0, float(data.get("progress"))))
                self.registry.update_run(self._last_run_id, **changes)
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        if self._run_dir:
            try:
                os.makedirs(self._run_dir, exist_ok=True)
                with open(os.path.join(self._run_dir, "events.jsonl"), "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False,
                                       default=str) + "\n")
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _start_run(self, title, run_id=""):
        self._ensure_events()
        self._cancel.clear()
        self._pause.clear()
        rid = run_id or ("computer:" + str(int(time.time() * 1000)))
        self._last_run_id = rid
        try:
            from core.agent_artifacts import maybe_cleanup
            maybe_cleanup(getattr(self.trunk, "base", os.getcwd()))
        except Exception as e:  # 静默是故意的 - 清理失败不影响任务
            _x6_swallowed(__name__, e, "best-effort fallback")
        self._rollback_items = []
        self._rollback_store = None
        self._approved_action_ids = set()
        self.registry.start_run("computer", title, run_id=rid,
                                budget={"max_seconds": 600})
        self._run_dir = self._run_base()
        os.makedirs(self._run_dir, exist_ok=True)
        from core.computer_rollback import FileRollbackStore
        self._rollback_store = FileRollbackStore(
            getattr(self.trunk, "base", os.getcwd()), self._run_dir)
        self._rollback_items = self._rollback_store.items
        self._emit("run_start", {"step": "开始电脑任务", "progress": 0.02})
        return rid

    def _finish_run(self, rid, status, error=""):
        self.registry.finish_run(rid, status, error)
        try:
            if self._rollback_store is not None:
                self._rollback_store.save(rid)
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")

    def run_actions(self, actions, *, run_id="", title="电脑操作任务",
                    verify_each=True, max_retries=1, approval_cb=None):
        rid = self._start_run(title, run_id=run_id)
        trace = []
        try:
            for i, raw in enumerate(actions or []):
                self._check_control()
                action = validate_action(raw)
                if callable(approval_cb):
                    if not approval_cb([action]):
                        self._finish_run(rid, "cancelled", "用户拒绝动作")
                        return {"ok": False, "cancelled": True,
                                "run_id": rid, "trace": trace}
                    self._approved_action_ids.add(action.get("action_id"))
                self.registry.update_run(
                    rid, current_step=action_summary(action),
                    progress=round(i / max(1, len(actions)), 3))
                self._emit("step_start", {"step": action_summary(action),
                                          "action": action,
                                          "progress": i / max(1, len(actions))})
                before = self.observe() if verify_each else {}
                if before:
                    before["file"] = self._file_sig(
                        (action.get("args") or {}).get("path")
                        or (action.get("target") or {}).get("path"))
                result = self.execute(action)
                verified = (self.verify(action, result, before)
                            if verify_each else {"ok": result.get("ok"),
                                                 "reason": ""})
                attempts = 0
                while not (result.get("ok") and verified.get("ok")) \
                        and attempts < max_retries:
                    attempts += 1
                    self._sleep(0.3)
                    result = self.execute(action)
                    verified = (self.verify(action, result, before)
                                if verify_each else {"ok": result.get("ok"),
                                                     "reason": ""})
                item = {"action": action, "result": result,
                        "verified": verified, "attempts": attempts,
                        "before_screenshot": (before or {}).get("screenshot", ""),
                        "after_screenshot": result.get("after_screenshot", "")}
                trace.append(item)
                self._emit("step_done", {
                    "step": action_summary(action),
                    "ok": bool(result.get("ok") and verified.get("ok")),
                    "result": result.get("output", ""),
                    "verify": verified.get("reason", ""),
                    "attempts": attempts,
                    "progress": (i + 1) / max(1, len(actions)),
                })
                if not (result.get("ok") and verified.get("ok")):
                    self._finish_run(rid, "failed", verified.get("reason", "动作失败"))
                    return {"ok": False, "run_id": rid, "error":
                            verified.get("reason") or result.get("output") or "动作失败",
                            "trace": trace, "rollback_items": self._rollback_items}
            self._finish_run(rid, "completed")
            self._emit("done", {"step": "电脑任务完成", "progress": 1.0,
                                "trace": trace})
            return {"ok": True, "run_id": rid, "trace": trace,
                    "rollback_items": self._rollback_items}
        except AgentCancelled:
            self._finish_run(rid, "cancelled", "用户取消")
            self._emit("cancelled", {"step": "任务已取消"})
            return {"ok": False, "cancelled": True, "run_id": rid,
                    "error": "用户取消", "trace": trace}
        except Exception as e:
            self._finish_run(rid, "failed", str(e)[:300])
            self._emit("failed", {"step": "电脑任务失败", "error": str(e)[:300]})
            return {"ok": False, "run_id": rid, "error": str(e)[:300],
                    "trace": trace}

    def run_goal(self, goal, *, snapshot=None, max_retries=1,
                 approval_cb=None, title=""):
        """兼容旧接口：先规划完整动作列表，再执行。"""
        snap = snapshot or self.observe()
        actions = self.plan_goal(goal, snap)
        if callable(approval_cb):
            if not approval_cb(actions):
                return {"ok": False, "cancelled": True, "actions": actions}
        return self.run_actions(actions, title=title or goal,
                                verify_each=True, max_retries=max_retries)

    def run_goal_dynamic(self, goal, *, snapshot=None, max_steps=None,
                         approval_cb=None, title="", max_retries=2):
        """真正 Observe -> Plan(单步) -> Act -> Verify -> Replan 循环。"""
        rid = self._start_run(title or goal)
        trace = []
        feedback = ""
        try:
            for step_no in range(1, max(1, int(max_steps or self.max_steps)) + 1):
                self._check_control()
                snap = self.observe()
                self._emit("observe", {
                    "step": "观察屏幕（第 %d 步）" % step_no,
                    "screenshot": snap.get("screenshot", ""),
                    "active_window": snap.get("active_window", ""),
                    "elements": len(snap.get("elements") or []),
                    "progress": min(0.9, step_no / max(1, self.max_steps)),
                })
                decision = self.plan_next(goal, snap, trace, feedback)
                if decision.get("done"):
                    self._finish_run(rid, "completed")
                    self._emit("done", {"step": decision.get("message", "目标完成"),
                                        "progress": 1.0, "trace": trace})
                    return {"ok": True, "run_id": rid, "trace": trace,
                            "message": decision.get("message", "目标完成"),
                            "rollback_items": self._rollback_items}
                action = validate_action(decision["action"])
                if callable(approval_cb):
                    self.registry.update_run(rid, status="waiting_approval")
                    self._emit("approval_wait", {"step": "等待动作确认",
                                                 "action": action})
                    if not approval_cb([action]):
                        self._finish_run(rid, "cancelled", "用户拒绝动作")
                        return {"ok": False, "cancelled": True, "run_id": rid,
                                "trace": trace}
                    self._approved_action_ids.add(action.get("action_id"))
                    self.registry.update_run(rid, status="running")
                before = snap
                before["file"] = self._file_sig(
                    (action.get("args") or {}).get("path")
                    or (action.get("target") or {}).get("path"))
                result = self.execute(action)
                verified = self.verify(action, result, before)
                attempts = 0
                while not (result.get("ok") and verified.get("ok")) \
                        and attempts < max_retries:
                    attempts += 1
                    self._emit("retry", {
                        "step": "动作未成功，重新观察后重试",
                        "action": action_summary(action),
                        "reason": verified.get("reason", ""),
                        "attempt": attempts,
                        "repair": repair_strategy(action, verified, attempts)})
                    self._sleep(0.4)
                    snap2 = self.observe()
                    before = snap2
                    before["file"] = self._file_sig(
                        (action.get("args") or {}).get("path")
                        or (action.get("target") or {}).get("path"))
                    result = self.execute(action)
                    verified = self.verify(action, result, before)
                item = {"action": action, "result": result,
                        "verified": verified, "attempts": attempts,
                        "repair": repair_strategy(action, verified, attempts)
                        if attempts else [],
                        "thought": decision.get("thought", ""),
                        "before_screenshot": before.get("screenshot", ""),
                        "after_screenshot": result.get("after_screenshot", "")}
                trace.append(item)
                self._emit("step_done", {
                    "step": action_summary(action),
                    "ok": bool(result.get("ok") and verified.get("ok")),
                    "result": result.get("output", ""),
                    "verify": verified.get("reason", ""),
                    "screenshot": result.get("after_screenshot", ""),
                    "attempts": attempts,
                    "progress": min(0.95, step_no / max(1, self.max_steps)),
                })
                if not (result.get("ok") and verified.get("ok")):
                    feedback = ("上一步失败：动作=%s；结果=%s；验证=%s。"
                                "请重新观察并换一种定位/方法。"
                                % (action_summary(action),
                                   result.get("output", ""),
                                   verified.get("reason", "")))
                else:
                    feedback = ""
            self._finish_run(rid, "failed", "达到最大步数")
            self._emit("failed", {"step": "达到最大步数，任务未完成",
                                  "progress": 1.0})
            return {"ok": False, "run_id": rid,
                    "error": "达到最大步数，任务未完成",
                    "trace": trace, "rollback_items": self._rollback_items}
        except AgentCancelled:
            self._finish_run(rid, "cancelled", "用户取消")
            self._emit("cancelled", {"step": "任务已取消"})
            return {"ok": False, "cancelled": True, "run_id": rid,
                    "error": "用户取消", "trace": trace}
        except Exception as e:
            self._finish_run(rid, "failed", str(e)[:300])
            self._emit("failed", {"step": "电脑任务失败", "error": str(e)[:300]})
            return {"ok": False, "run_id": rid, "error": str(e)[:300],
                    "trace": trace}

    def rollback_run(self, run_id=""):
        rid = run_id or self._last_run_id
        base = getattr(self.trunk, "base", os.getcwd())
        if self._rollback_store is not None and (
                not rid or rid == self._last_run_id):
            items = self._rollback_store.items
        else:
            from core.computer_rollback import FileRollbackStore
            items = FileRollbackStore.load(base, rid)
        try:
            from core.computer_rollback import FileRollbackStore
            restored = FileRollbackStore.rollback(items, self._ctrl())
        except Exception as e:
            return {"ok": False, "error": str(e)[:300], "restored": []}
        self._emit("rollback", {"step": "已回滚电脑任务文件操作",
                                "restored": restored})
        return {"ok": True, "restored": restored}
