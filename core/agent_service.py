# -*- coding: utf-8 -*-
"""后台代码任务服务（批次 46.1/46.2）。

为什么需要它
------------
原来工作台点"开始"是在 UI 线程里同步跑 Agent：进度条要手动
``processEvents``，一跑十几分钟，窗口看着像卡死；关闭窗口还可能把任务
一起带走。这个服务把"执行"从界面里拆出来，只管四件事：

* **单写者**：同一项目同一时刻只允许一个 job 真正执行，第二个 ``run_next``
  直接返回 ``busy``，避免两个任务同时改同一批文件；
* **队列消费**：job 状态与断点仍落在 ``data/code_jobs/queue.json``，
  ``resume(job_id)`` 只是把 ``paused/failed/interrupted`` 重新置为 ``queued``，
  续跑上下文由 ``CodeAgent`` 按目标重建；
* **取消/暂停**：``cancel`` 同时置取消标志、调 ``orchestrator.cancel()``、
  释放所有等待中的审批，保证线程能在一两秒内退出；
* **审批代理**：后台线程不能弹 Qt 对话框，所以审批变成"事件 + 等待"：
  服务 emit ``approval``（带 request_id），UI 在 GUI 线程弹窗后调用
  ``answer(request_id, ok)``；超时或取消一律按拒绝处理（fail-closed）。

L2 自动档（46.2）：
* ``code_agent.auto_apply`` 默认 **关**；打开后 L2 自动应用 low/medium
  风险改动，high 仍走审批；L3 在计划确认后连 high 也自动应用；
* 风险分级复用 ``core.patch_protocol.classify_patch``；自动应用会 emit
  ``auto_apply``，界面负责顶部提示与撤销入口（备份清单由 Agent 产出）。

本模块不导入 Qt，可单独跑单测；GUI 侧只用 ``AgentServiceWorker`` 转发信号。
"""
from __future__ import annotations

import os
import threading
import time
import uuid

from core.code_task_queue import get_code_queue

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_MODE = "L2"
RESUMABLE = {"paused", "failed", "interrupted"}


def _rule(trunk, name, default):
    try:
        return trunk.rule(name, default)
    except Exception as e:
        _x6_swallowed(__name__, e, "read rule " + str(name))
        return default


class AgentService:
    """代码任务执行服务；线程安全，UI 只通过事件/查询接口访问。"""

    def __init__(self, trunk=None, root=None, queue=None, runner=None,
                 event_cb=None, approval_timeout=600):
        self.trunk = trunk
        self.root = os.path.abspath(root or getattr(trunk, "base", ".") or ".")
        self.queue = queue or get_code_queue(self.root)
        self._runner = runner
        self._event_cb = event_cb
        self.approval_timeout = max(1, int(approval_timeout or 600))
        self._lock = threading.RLock()
        self._listeners = []
        self._pending = {}
        self._active_job = None
        self._orchestrator = None
        self._cancel = threading.Event()
        self.last_result = None
        self._closed = False

    # ---------------------------------------------------------- 事件
    def add_listener(self, listener):
        if not callable(listener):
            return False
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)
        return True

    def remove_listener(self, listener):
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)
                return True
        return False

    def _emit(self, event, data=None):
        payload = data if isinstance(data, dict) else {}
        with self._lock:
            listeners = list(self._listeners)
            cb = self._event_cb
        for listener in listeners:
            try:
                listener(str(event), payload)
            except Exception as e:  # 静默是故意的 - 一个监听器坏了不能拖垮任务
                _x6_swallowed(__name__, e, "service listener")
        if callable(cb):
            try:
                cb(str(event), payload)
            except Exception as e:  # 静默是故意的 - 回调异常不影响执行
                _x6_swallowed(__name__, e, "service event callback")

    # ---------------------------------------------------------- 提交 / 排队
    def submit(self, goal, *, mode=None, open_files=None, selection="",
               max_rounds=None, explicit=None):
        goal = str(goal or "").strip()
        if not goal:
            return {"ok": False, "error": "目标为空"}
        job = self.queue.enqueue(goal, max_rounds=max_rounds,
                                 open_files=open_files)
        mode = str(mode or _rule(self.trunk, "code_agent.mode", DEFAULT_MODE)
                   or DEFAULT_MODE).upper()
        try:
            self.queue.update(job["job_id"], mode=mode, selection=str(selection or ""),
                              explicit=str(explicit or ""))
            job = self.queue.get(job["job_id"]) or job
        except Exception as e:  # 静默是故意的 - 附加字段失败不影响入队
            _x6_swallowed(__name__, e, "annotate job")
        self._emit("queued", {"step": "任务已入队", "job_id": job["job_id"],
                              "goal": goal, "mode": mode})
        return {"ok": True, "job_id": job["job_id"], "job": job}

    def resume(self, job_id):
        job = self.queue.get(job_id)
        if not job:
            return {"ok": False, "error": "任务不存在"}
        if str(job.get("status") or "") not in RESUMABLE:
            return {"ok": False, "error": "该任务不在可续跑状态"}
        self.queue.update(job_id, status="queued", error="")
        self._emit("queued", {"step": "任务已重新入队", "job_id": job_id,
                              "resume": True})
        return {"ok": True, "job_id": job_id}

    def queued(self):
        return self.queue.next_queued()

    def busy(self):
        with self._lock:
            return self._active_job is not None

    # ---------------------------------------------------------- 执行
    def run_next(self):
        """在调用线程执行下一个 queued job；没任务返回 ``idle``。"""
        with self._lock:
            if self._active_job is not None:
                return {"ok": False, "busy": True,
                        "job_id": self._active_job.get("job_id")}
            job = self.queue.next_queued()
            if not job:
                return {"ok": True, "idle": True}
            self._active_job = job
            self._cancel.clear()
        try:
            return self._run(job)
        finally:
            with self._lock:
                self._active_job = None
                self._orchestrator = None

    def _run(self, job):
        job_id = str(job.get("job_id") or "")
        self.queue.mark_running(job_id)
        self._emit("job_start", {"step": "后台任务开始", "job_id": job_id,
                                 "goal": job.get("goal", ""),
                                 "mode": job.get("mode") or DEFAULT_MODE})
        runner = self._runner or self._default_runner
        try:
            result = runner(self, job) or {}
        except Exception as e:  # 静默是故意的 - 服务边界兜底，结果里带回错误
            _x6_swallowed(__name__, e, "run job")
            result = {"ok": False, "error": str(e)[:400]}
        if not isinstance(result, dict):
            result = {"ok": False, "error": "任务返回了非字典结果"}
        if self._cancel.is_set() and not result.get("cancelled"):
            result = dict(result)
            result["cancelled"] = True
            result.setdefault("error", "用户取消")
            result["ok"] = False
        self.last_result = result
        self.queue.mark_done(job_id, result)
        self._emit("job_done", {"step": "任务结束", "job_id": job_id,
                                "ok": bool(result.get("ok")),
                                "cancelled": bool(result.get("cancelled")),
                                "stop_reason": result.get("stop_reason", "")})
        if not result.get("cancelled"):
            self._queue_personality(
                "task_done" if result.get("ok") else "error",
                result.get("goal") or job_id)
        return result

    def _queue_personality(self, event, detail=""):
        """48.3：任务结束事件入队，由人格模块在合适时机主动说一句。"""
        try:
            pers = (getattr(self.trunk, "modules", {}) or {}).get("personality")
            if pers is None and self.trunk is not None:
                pers = self.trunk._load_lazy("personality")
            if pers is not None and hasattr(pers, "queue_proactive"):
                pers.queue_proactive(event, detail)
        except Exception as e:
            _x6_swallowed(__name__, e, "queue personality event")

    def _default_runner(self, service, job):
        from core.agent_orchestrator import AgentOrchestrator
        job_id = str(job.get("job_id") or "")
        orch = AgentOrchestrator(
            self.trunk, root=self.root, event_cb=self._emit,
            approval_cb=lambda kind, payload: self._approve(job, kind, payload),
            max_code_rounds=job.get("max_rounds"),
            open_files=job.get("open_files") or [],
            selection=str(job.get("selection") or ""))
        self._orchestrator = orch

        def checkpoint(state):
            try:
                self.queue.checkpoint(job_id, state)
            except Exception as e:  # 静默是故意的 - 断点失败不阻塞任务
                _x6_swallowed(__name__, e, "service checkpoint")

        try:
            return orch.run(str(job.get("goal") or ""),
                            explicit=job.get("explicit") or None,
                            resume_state=self.queue.checkpoint_of(job),
                            checkpoint_cb=checkpoint) or {}
        finally:
            self._orchestrator = None

    # ---------------------------------------------------------- 控制
    def cancel(self, job_id=None):
        with self._lock:
            active = self._active_job
            if job_id and (not active or active.get("job_id") != job_id):
                job = self.queue.get(job_id)
                if job and str(job.get("status")) == "queued":
                    self.queue.update(job_id, status="cancelled", error="用户取消")
                    self._emit("cancelled", {"step": "排队任务已取消",
                                             "job_id": job_id})
                    return {"ok": True, "job_id": job_id}
                return {"ok": False, "error": "任务不在运行中"}
            if not active:
                # 没有活动 job 时也可能有人在等审批（例如刚结束/重入），
                # 一律按拒绝释放，避免等待线程挂住。
                self._cancel.set()
            else:
                self._cancel.set()
                orch = self._orchestrator
        if not active:
            for request_id in self._release_pending(False):
                self._emit("approval_cancelled", {"step": "审批已取消",
                                                  "request_id": request_id})
            return {"ok": False, "error": "当前没有运行中的任务"}
        for request_id in self._release_pending(False):
            self._emit("approval_cancelled", {"step": "审批已取消",
                                              "request_id": request_id})
        if orch is not None:
            try:
                orch.cancel()
            except Exception as e:  # 静默是故意的 - 取消失败也要让线程退出
                _x6_swallowed(__name__, e, "cancel orchestrator")
        self._emit("cancel_requested", {"step": "正在取消任务",
                                        "job_id": active.get("job_id")})
        return {"ok": True, "job_id": active.get("job_id")}

    def pause(self):
        orch = self._orchestrator
        if orch is None:
            return {"ok": False, "error": "当前没有运行中的任务"}
        try:
            return orch.pause() or {"ok": True}
        except Exception as e:  # 静默是故意的 - 暂停失败不影响任务
            _x6_swallowed(__name__, e, "pause job")
            return {"ok": False, "error": str(e)[:200]}

    def resume_paused(self):
        orch = self._orchestrator
        if orch is None:
            return {"ok": False, "error": "当前没有暂停的任务"}
        try:
            return orch.resume() or {"ok": True}
        except Exception as e:  # 静默是故意的 - 继续失败不影响任务
            _x6_swallowed(__name__, e, "resume job")
            return {"ok": False, "error": str(e)[:200]}

    def close(self):
        """窗口关闭时调用：取消任务并清空监听器（不阻塞等待线程）。"""
        self.cancel()
        with self._lock:
            self._closed = True
            self._listeners = []
        self._release_pending(False)
        _SERVICES.pop(self.root, None)

    # ---------------------------------------------------------- 审批
    def _approve(self, job, kind, payload):
        mode = str(job.get("mode") or DEFAULT_MODE).upper()
        risk = None
        if kind == "code" and isinstance(payload, dict):
            try:
                from core.patch_protocol import (auto_apply_enabled,
                                                 classify_patch)
                risk = classify_patch(self.root, payload)
                if auto_apply_enabled(self.trunk) and mode in ("L2", "L3"):
                    allowed = ({"low", "medium"} if mode == "L2"
                               else {"low", "medium", "high"})
                    if str(risk.get("level")) in allowed:
                        self._emit("auto_apply", {
                            "step": "低风险改动已自动应用（可撤销）",
                            "risk": risk, "files": risk.get("files"),
                            "diff_lines": risk.get("diff_lines")})
                        return True
            except Exception as e:  # 静默是故意的 - 分级失败退回人工审批
                _x6_swallowed(__name__, e, "auto apply risk")
        self._emit("approval_required", {"step": "改动需要确认", "kind": kind,
                                         "risk": risk})
        return self._ask(kind, payload)

    def _ask(self, kind, payload):
        request_id = "approval_" + uuid.uuid4().hex[:10]
        request = {"event": threading.Event(), "decision": False,
                   "kind": str(kind), "created": time.time()}
        with self._lock:
            if self._closed:
                return False
            self._pending[request_id] = request
        self._emit("approval", {"step": "等待确认", "request_id": request_id,
                                "kind": str(kind), "payload": payload})
        deadline = time.time() + self.approval_timeout
        while time.time() < deadline:
            if request["event"].wait(0.5):
                break
            if self._cancel.is_set():
                break
        with self._lock:
            self._pending.pop(request_id, None)
        if not request["event"].is_set():
            self._emit("approval_timeout", {"step": "审批超时，按拒绝处理",
                                            "request_id": request_id})
            return False
        return bool(request.get("decision"))

    def answer(self, request_id, accepted):
        """GUI 线程在弹窗结束后调用；找不到请求返回 False。"""
        with self._lock:
            request = self._pending.pop(str(request_id or ""), None)
        if request is None:
            return False
        request["decision"] = bool(accepted)
        request["event"].set()
        return True

    def _release_pending(self, decision):
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        for _, request in pending:
            request["decision"] = bool(decision)
            request["event"].set()
        return [rid for rid, _ in pending]

    # ---------------------------------------------------------- 查询
    def stats(self):
        with self._lock:
            active = self._active_job
            pending = len(self._pending)
            listeners = len(self._listeners)
        return {"busy": active is not None,
                "active_job": (active or {}).get("job_id", ""),
                "queued": len(self.queue.jobs("queued")),
                "pending_approvals": pending,
                "listeners": listeners,
                "root": self.root}


_SERVICES = {}


def get_agent_service(trunk=None, root=None, **kwargs):
    """按项目根复用服务实例，避免多个面板各跑一个单写者锁。"""
    key = os.path.abspath(root or getattr(trunk, "base", ".") or ".")
    service = _SERVICES.get(key)
    if service is None:
        service = AgentService(trunk, root=key, **kwargs)
        _SERVICES[key] = service
    return service
