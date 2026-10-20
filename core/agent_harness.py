# -*- coding: utf-8 -*-
"""统一 Agent 运行状态、错误信封和活动注册表。

这是产品体验方案 Sprint 1 的底座：
    * 所有长任务在 RunRegistry 里登记
    * 任务状态变化统一推送
    * 错误转成结构化 envelope（code/title/message/next_action）
    * 活动中心、任务中心、聊天错误卡片共用同一份数据

不依赖 Qt，便于单元测试。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Dict, Iterable, List, Optional


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"pending", "planning", "running", "paused", "waiting_approval"}

# 错误 code -> 用户可读信息 + 唯一下一步。
# action id 与 gui/guidance.py / UIModeMixin._run_guidance_action 保持一致。
ERROR_SPECS: Dict[str, Dict] = {
    "MODEL_NOT_CONFIGURED": {
        "title": "模型还没配置好",
        "message": "当前回复可能失败，先完成模型配置。",
        "action": "open_model_settings",
        "action_label": "去设置模型",
    },
    "PERMISSION_DENIED": {
        "title": "权限被拒绝",
        "message": "这次操作没有获得授权，可以重新授权或去安全中心查看原因。",
        "action": "open_security_center",
        "action_label": "重新授权 / 去安全中心",
    },
    "NETWORK_DENIED": {
        "title": "网络被拒绝",
        "message": "安全策略拦截了这次网络请求，去安全中心查看网络事件。",
        "action": "open_security_network_events",
        "action_label": "查看安全中心网络事件",
    },
    "TOOL_NOT_FOUND": {
        "title": "工具不存在",
        "message": "当前模块没有提供这个工具，去插件市场安装或启用对应模块。",
        "action": "open_plugin_market",
        "action_label": "去插件市场",
    },
    "TASK_TIMEOUT": {
        "title": "任务超时",
        "message": "可以增加任务预算后继续，或者把目标拆小一点再试。",
        "action": "increase_task_budget",
        "action_label": "增加预算 / 继续任务",
    },
    "TASK_FAILED": {
        "title": "任务失败",
        "message": "先重试失败步骤；如果仍然失败，再查看日志定位原因。",
        "action": "retry_failed_step",
        "action_label": "重试失败步骤",
    },
    "FILE_CONFLICT": {
        "title": "文件已被修改",
        "message": "目标文件在应用补丁前发生了变化，已停止覆盖。",
        "action": "review_diff",
        "action_label": "查看 diff / 重新生成",
    },
    "TEST_FAILED": {
        "title": "测试未通过",
        "message": "修改已应用，但测试没有通过；可以自动修复或查看失败测试。",
        "action": "auto_fix_failed_tests",
        "action_label": "自动修复失败测试",
    },
}


def _now() -> float:
    return time.time()


def _new_run_id(prefix: str = "run") -> str:
    return "%s_%s_%s" % (prefix, time.strftime("%Y%m%d_%H%M%S"),
                         uuid.uuid4().hex[:6])


def normalize_error(error, code: Optional[str] = None) -> Dict:
    """把异常、文本或任务错误转成统一错误信封。

    返回字段稳定：
        ok / code / title / message / cause / next_action / technical_detail
    """
    if isinstance(error, dict):
        src = dict(error)
        code = code or src.get("code") or src.get("错误码")
        technical = src.get("technical_detail") or src.get("技术细节") \
            or src.get("error") or src.get("错误") or ""
        text = str(src.get("message") or src.get("msg") or technical or "")
    else:
        src = {}
        technical = str(error or "")
        text = technical

    if not code:
        low = text.lower()
        rules = (
            ("MODEL_NOT_CONFIGURED", ("模型未配置", "模型没配置", "llm未加载",
                                      "api key", "no model")),
            ("NETWORK_DENIED", ("网络被拒绝", "网络策略", "network denied",
                                "net_guard", "连接被拒绝", "winerror 10061")),
            ("PERMISSION_DENIED", ("权限", "拒绝", "denied", "forbidden",
                                   "unauthorized")),
            ("TOOL_NOT_FOUND", ("工具不存在", "没有方法", "not found",
                                "no such tool")),
            ("FILE_CONFLICT", ("文件已被修改", "hash", "冲突", "conflict",
                               "base_hash")),
            ("TEST_FAILED", ("测试失败", "test failed", "assertionerror",
                             "pytest", "测试未通过")),
            ("TASK_TIMEOUT", ("任务超时", "timeout", "超时")),
        )
        for c, needles in rules:
            if any(n.lower() in low for n in needles):
                code = c
                break
        else:
            code = "TASK_FAILED"
    code = str(code).upper()
    spec = ERROR_SPECS.get(code) or ERROR_SPECS["TASK_FAILED"]
    # 允许调用方覆盖展示文案，但不能没有下一步
    title = src.get("title") or spec["title"]
    message = src.get("message") or spec["message"]
    next_action = src.get("next_action") or {
        "id": spec["action"], "label": spec["action_label"],
    }
    return {
        "ok": False,
        "code": code,
        "title": str(title),
        "message": str(message),
        "cause": str(src.get("cause") or technical)[:500],
        "next_action": next_action,
        "technical_detail": str(technical)[:2000],
    }


def error_text(error, code: Optional[str] = None) -> str:
    env = normalize_error(error, code)
    return "%s\n%s" % (env["title"], env["message"])


class RunRegistry:
    """线程安全的运行中活动注册表。

    设计成单例（get_run_registry），任意模块都可以登记活动；
    活动中心只订阅这一份数据，不重复扫描任务/线程。
    """

    def __init__(self, max_runs: int = 500):
        self._lock = threading.RLock()
        self._runs: Dict[str, Dict] = {}
        self._subscribers: List[Callable] = []
        self.max_runs = max(20, int(max_runs or 500))

    # ---------- 基础登记 ----------
    def start_run(self, kind: str, title: str, *, run_id: str = "",
                  task_id: str = "", trace_id: str = "",
                  status: str = "running", budget: Optional[Dict] = None,
                  metadata: Optional[Dict] = None) -> Dict:
        rid = run_id or _new_run_id(kind)
        now = _now()
        run = {
            "run_id": rid,
            "kind": str(kind or "job"),
            "title": str(title or "未命名活动"),
            "status": str(status or "running"),
            "current_step": "",
            "progress": 0.0,
            "started_at": now,
            "updated_at": now,
            "finished_at": 0,
            "budget": dict(budget or {}),
            "usage": {},
            "waiting_for": "",
            "error": "",
            "task_id": str(task_id or ""),
            "trace_id": str(trace_id or ""),
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            # 保留已存在 run 的创建时间，便于重复启动时更新同一项
            old = self._runs.get(rid)
            if old:
                run["started_at"] = old.get("started_at", now)
            self._runs[rid] = run
            self._prune_locked()
        self._notify(run, "started")
        return dict(run)

    def _prune_locked(self):
        """只淘汰已结束的旧 run，保留全部活跃任务。"""
        overflow = len(self._runs) - self.max_runs
        if overflow <= 0:
            return []
        terminal = sorted(
            ((r.get("finished_at") or r.get("updated_at") or 0), rid)
            for rid, r in self._runs.items()
            if r.get("status") in TERMINAL_STATUSES)
        removed = []
        for _ts, rid in terminal[:overflow]:
            self._runs.pop(rid, None)
            removed.append(rid)
        return removed

    def prune(self):
        with self._lock:
            return self._prune_locked()

    def update_run(self, run_id: str, **changes) -> Optional[Dict]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None
            for k, v in changes.items():
                if k in ("run_id", "started_at"):
                    continue
                if k in ("budget", "usage", "metadata") and isinstance(v, dict):
                    run[k] = dict(v)
                else:
                    run[k] = v
            run["updated_at"] = _now()
            if run.get("status") in TERMINAL_STATUSES and not run.get("finished_at"):
                run["finished_at"] = run["updated_at"]
            out = dict(run)
        self._notify(out, "updated")
        return out

    def finish_run(self, run_id: str, status: str = "completed",
                   error: str = "") -> Optional[Dict]:
        return self.update_run(run_id, status=status, error=str(error or ""),
                               finished_at=_now())

    def remove_run(self, run_id: str) -> bool:
        with self._lock:
            existed = run_id in self._runs
            self._runs.pop(run_id, None)
        if existed:
            self._notify({"run_id": run_id}, "removed")
        return existed

    # ---------- TaskRuntime 同步 ----------
    def upsert_task(self, task: Dict, event: str = "",
                    detail: str = "") -> Optional[Dict]:
        if not isinstance(task, dict) or not task.get("id"):
            return None
        steps = task.get("steps") or []
        done = sum(1 for s in steps if s.get("status") in ("done", "cancelled"))
        running = next((s for s in steps if s.get("status") == "running"), None)
        failed = next((s for s in steps if s.get("status") == "failed"), None)
        current = running or failed
        rid = "task:" + str(task["id"])
        status = str(task.get("status") or "pending")
        budget = dict(task.get("budget") or {})
        usage = dict(task.get("usage") or {})
        error = str(task.get("error") or "")
        waiting = "用户确认" if status == "waiting_approval" else ""
        with self._lock:
            old = self._runs.get(rid)
            if not old:
                self.start_run(
                    "task", task.get("goal", "任务"), run_id=rid,
                    task_id=task.get("id", ""),
                    trace_id=task.get("trace_id", ""), status=status,
                    budget=budget, metadata={"event": event, "detail": detail})
                return self.update_run(
                    rid,
                    current_step=str((current or {}).get("title", "")),
                    progress=round(float(done) / max(1, len(steps)), 3),
                    usage=usage, waiting_for=waiting, error=error)
            # 统一更新
            old.update({
                "title": str(task.get("goal") or old.get("title") or "任务"),
                "status": status,
                "current_step": str((current or {}).get("title", "")
                                    or old.get("current_step", "")),
                "progress": round(float(done) / max(1, len(steps)), 3),
                "budget": budget,
                "usage": usage,
                "waiting_for": waiting,
                "error": error,
                "updated_at": _now(),
                "metadata": dict(old.get("metadata") or {},
                                 event=event, detail=detail),
            })
            if status in TERMINAL_STATUSES and not old.get("finished_at"):
                old["finished_at"] = old["updated_at"]
            out = dict(old)
        self._notify(out, event or "updated")
        return out

    def sync_tasks(self, tasks: Iterable[Dict]) -> None:
        for task in tasks or []:
            self.upsert_task(task, event="sync")

    # ---------- 查询 ----------
    def get_run(self, run_id: str) -> Optional[Dict]:
        with self._lock:
            run = self._runs.get(run_id)
            return dict(run) if run else None

    def list_runs(self, *, active_only=False, limit=100) -> List[Dict]:
        with self._lock:
            runs = [dict(x) for x in self._runs.values()]
        if active_only:
            runs = [x for x in runs if x.get("status") in ACTIVE_STATUSES]
        runs.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return runs[:limit]

    def active_runs(self) -> List[Dict]:
        return self.list_runs(active_only=True)

    def active_count(self) -> int:
        return len(self.active_runs())

    # ---------- 订阅 ----------
    def subscribe(self, callback: Callable) -> Callable:
        if callable(callback):
            self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: Callable) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, run: Dict, event: str) -> None:
        for cb in list(self._subscribers):
            try:
                cb(dict(run), event)
            except Exception:  # 静默是故意的
                pass


_registry = RunRegistry()


def get_run_registry() -> RunRegistry:
    return _registry


def reset_run_registry() -> RunRegistry:
    """测试用：清空注册表并返回单例。"""
    global _registry
    _registry = RunRegistry()
    return _registry

