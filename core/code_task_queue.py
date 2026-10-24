# -*- coding: utf-8 -*-
"""代码任务队列 + 断点续跑。

设计取舍
--------
* 队列只存"要做什么"和"做到第几轮"，不存模型上下文（体积大且易过期）；
  续跑时 CodeAgent 会按目标重新收集上下文，再带上 last_error / 指纹继续；
* 状态机：queued -> running -> completed | failed | paused | cancelled；
  进程崩溃时 running 会在下次加载时变成 interrupted（可续跑）；
* 队列文件 `data/code_jobs/queue.json` 原子写入，最多保留 100 条，
  避免像 agent_runs 那样无限增长。
"""
from __future__ import annotations

import json
import os
import time
import uuid

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

STATUS_DONE = {"completed", "failed", "cancelled"}
MAX_JOBS = 100


class CodeTaskQueue:
    def __init__(self, root):
        self.root = os.path.abspath(root or ".")
        self.dir = os.path.join(self.root, "data", "code_jobs")
        self.path = os.path.join(self.dir, "queue.json")
        self.data = self._load()

    # ---------------------------------------------------------- 存储
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("jobs"), list):
                for job in data["jobs"]:
                    if job.get("status") == "running":
                        job["status"] = "interrupted"
                return data
        except (OSError, ValueError):
            pass
        return {"version": 1, "jobs": []}

    def _save(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            data = self.data
            data["jobs"] = data["jobs"][-MAX_JOBS:]
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            _x6_swallowed(__name__, e, "save code task queue")

    # ---------------------------------------------------------- 查询
    def jobs(self, status=None):
        items = list(self.data.get("jobs") or [])
        if status:
            wanted = set(status) if isinstance(status, (list, tuple, set)) else {status}
            items = [j for j in items if j.get("status") in wanted]
        return items

    def get(self, job_id):
        for job in self.data.get("jobs") or []:
            if job.get("job_id") == job_id:
                return job
        return None

    def next_queued(self):
        for job in self.data.get("jobs") or []:
            if job.get("status") == "queued":
                return job
        return None

    def resumable(self):
        return self.jobs({"paused", "failed", "interrupted"})

    def checkpoint_of(self, job):
        state = (job or {}).get("checkpoint") or {}
        if not state:
            return {}
        return dict(state)

    # ---------------------------------------------------------- 变更
    def enqueue(self, goal, *, max_rounds=None, open_files=None):
        job = {
            "job_id": "job_" + uuid.uuid4().hex[:10],
            "goal": str(goal or "")[:4000],
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "round": 0,
            "max_rounds": max_rounds,
            "open_files": [str(x) for x in (open_files or [])],
            "stop_reason": "",
            "error": "",
            "checkpoint": {},
        }
        self.data.setdefault("jobs", []).append(job)
        self._save()
        return job

    def update(self, job_id, **fields):
        job = self.get(job_id)
        if not job:
            return None
        fields["updated_at"] = time.time()
        job.update(fields)
        self._save()
        return job

    def mark_running(self, job_id):
        return self.update(job_id, status="running", error="")

    def checkpoint(self, job_id, state):
        """CodeAgent 每轮结束回调：把轮次/错误/指纹落盘。"""
        state = dict(state or {})
        job = self.update(
            job_id, checkpoint=state, round=int(state.get("round") or 0),
            status="paused" if state.get("done") else "running")
        return job

    def mark_paused(self, job_id, error=""):
        return self.update(job_id, status="paused", error=str(error or "")[:500])

    def mark_done(self, job_id, result):
        result = result or {}
        status = "completed" if result.get("ok") else (
            "paused" if result.get("cancelled") else "failed")
        return self.update(
            job_id, status=status, stop_reason=str(result.get("stop_reason") or ""),
            round=int(result.get("rounds_used") or 0),
            error=str(result.get("error") or "")[:500])

    def remove_finished(self):
        self.data["jobs"] = [j for j in self.data.get("jobs") or []
                             if j.get("status") not in STATUS_DONE]
        self._save()

    def clear(self):
        self.data["jobs"] = []
        self._save()


_QUEUES = {}


def get_code_queue(root):
    """按项目根复用队列实例（避免多个面板各写一份 JSON）。"""
    key = os.path.abspath(root or ".")
    if key not in _QUEUES:
        _QUEUES[key] = CodeTaskQueue(key)
    return _QUEUES[key]
