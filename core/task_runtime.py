# -*- coding: utf-8 -*-
"""可持久化的 Agent 任务运行时。

状态机：pending -> planning -> running -> waiting_approval -> paused
        -> completed / failed / cancelled
每个任务写 data/task_runtime/{id}.json；进程重启后可继续查看/恢复 paused 任务。
"""
import hashlib
import json
import os
import threading
import time
import uuid

from core.trace import Trace

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class TaskRuntime:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.dir = os.path.join(self.base, "data", "task_runtime")
        os.makedirs(self.dir, exist_ok=True)
        self.trace = Trace(self.base)
        self._lock = threading.RLock()
        self._tasks = {}
        self._threads = {}
        self._pause = {}
        self._cancel = {}
        self._subscribers = []
        self._idem_path = os.path.join(self.dir, "idempotency.jsonl")
        self._idem = self._load_idem()
        self._load()

    def _path(self, task_id):
        return os.path.join(self.dir, "%s.json" % task_id)

    def _load_idem(self):
        out = {}
        try:
            for ln in open(self._idem_path, encoding="utf-8").read().splitlines()[-2000:]:
                rec = json.loads(ln)
                if rec.get("key"):
                    out[rec["key"]] = rec
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback
        return out

    @staticmethod
    def _arg_hash(args):
        try:
            raw = json.dumps(args or {}, ensure_ascii=False, sort_keys=True,
                             default=str)
        except Exception:
            raw = repr(args)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _idem_key(self, task, step):
        return "%s:%s:%s:%s" % (
            task.get("id"), step.get("id"), step.get("tool"),
            self._arg_hash(step.get("args")))

    def _remember_idem(self, key, result):
        rec = {"key": key, "time": time.time(),
               "result": str(result)[:1000]}
        self._idem[key] = rec
        try:
            with open(self._idem_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback

    def _load(self):
        for f in os.listdir(self.dir):
            if not f.endswith(".json"):
                continue
            try:
                d = json.load(open(os.path.join(self.dir, f), encoding="utf-8"))
                if d.get("id"):
                    self._tasks[d["id"]] = d
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback

    def _save(self, task):
        task["updated_at"] = time.time()
        tmp = self._path(task["id"]) + ".tmp"
        with self._lock:
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(task, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path(task["id"]))
                self._tasks[task["id"]] = json.loads(json.dumps(task))
                return True
            except Exception as e:
                self.trace.record({"kind": "task_save_error",
                                   "task_id": task.get("id"),
                                   "error": str(e)[:160]})
                return False

    def _emit(self, task, event, detail=""):
        self.trace.record({"kind": event, "task_id": task.get("id"),
                           "status": task.get("status"), "detail": detail})
        # 统一活动注册表：任务中心、活动中心、聊天结果卡片都从这里取状态。
        try:
            from core.agent_harness import get_run_registry
            get_run_registry().upsert_task(task, event, detail)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - 活动注册表坏了不能影响任务本身
        for cb in list(self._subscribers):
            try:
                cb(task, event, detail)
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback

    def subscribe(self, callback):
        self._subscribers.append(callback)

    def create(self, goal, *, mode="agent"):
        tid = "task_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        task = {"id": tid, "goal": str(goal or "").strip(), "mode": mode,
                "status": "pending", "created_at": time.time(),
                "updated_at": time.time(), "trace_id": "trace_" + tid,
                "budget": {"max_steps": 8, "max_seconds": 300,
                           "max_tokens": 20000},
                "steps": [], "checkpoint": {}, "final": "", "error": ""}
        with self._lock:
            self._tasks[tid] = task
        self._save(task)
        self._emit(task, "created")
        return task

    def plan(self, task_id):
        task = self.get_task(task_id)
        if not task:
            return None
        task["status"] = "planning"
        self._save(task)
        steps = []
        try:
            if self.trunk:
                r = self.trunk.call("task_planner", "plan", task["goal"])
                raw = r.get("步骤") if isinstance(r, dict) else r
            else:
                raw = []
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []
        for i, s in enumerate(raw or [], 1):
            name = s.get("name") if isinstance(s, dict) else str(s)
            deps = s.get("deps", []) if isinstance(s, dict) else []
            if not isinstance(deps, list):
                deps = []
            steps.append({"id": "step_%d" % i, "title": str(name)[:120],
                          "deps": [str(d)[:80] for d in deps],
                          "status": "pending", "agent": "",
                          "tool": s.get("tool", "") if isinstance(s, dict) else "",
                          "args": s.get("args", {}) if isinstance(s, dict) else {},
                          "requires_approval": False,
                          "started_at": 0, "finished_at": 0,
                          "result_preview": "", "error": ""})
        # planner 的依赖写的是步骤名；统一转换成 step_id。
        name_to_id = {x["title"]: x["id"] for x in steps}
        for x in steps:
            x["deps"] = [name_to_id.get(d, d) for d in (x.get("deps") or [])]
        if not steps:
            steps = [{"id": "step_1", "title": "分析目标",
                      "status": "pending", "agent": "", "tool": "",
                      "args": {}, "requires_approval": False,
                      "started_at": 0, "finished_at": 0,
                      "result_preview": "", "error": ""}]
        task["steps"] = steps
        task["status"] = "pending"
        self._save(task)
        self._emit(task, "planned", "%d steps" % len(steps))
        return task

    def get_task(self, task_id):
        with self._lock:
            return json.loads(json.dumps(self._tasks.get(task_id) or {}))

    def list_tasks(self):
        with self._lock:
            return sorted([dict(t) for t in self._tasks.values()],
                          key=lambda x: x.get("created_at", 0), reverse=True)

    def _exec_step(self, task, step):
        if step.get("tool") and self.trunk:
            try:
                self.trunk.call("tool_caller", "__no__")
                tc = self.trunk.modules.get("tool_caller")
                info = (tc.tools.get(step["tool"]) if tc else None)
                if tc and info:
                    from core import security_policy
                    policy = security_policy.classify(step["tool"], info)
                    key = self._idem_key(task, step)
                    if not policy.get("readonly") and key in self._idem:
                        return {"ok": True, "结果": self._idem[key].get("result", ""),
                                "_idempotent_replay": True}
                    r = tc._dispatch(info, step.get("args") or {},
                                     task["goal"], step["tool"])
                    if not policy.get("readonly"):
                        self._remember_idem(key, r)
                    from core.tool_result import normalize
                    return normalize(r)
            except Exception as e:
                return {"ok": False, "错误": str(e)[:120]}
        try:
            llm = self.trunk.modules.get("llm") if self.trunk else None
            if not llm:
                return {"ok": False, "错误": "LLM未加载"}
            prompt = "目标：%s\n当前步骤：%s\n请只输出这一步的结果。" % (
                task["goal"], step.get("title", ""))
            return {"ok": True, "结果": llm.chat(prompt)}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:120]}

    def _run(self, task_id):
        task = self.get_task(task_id)
        if not task:
            return
        self._pause[task_id] = threading.Event()
        self._cancel[task_id] = threading.Event()
        task["status"] = "running"
        task.setdefault("usage", {"tool_calls": 0, "tokens": 0, "cost": 0.0})
        budget = task.get("budget", {})
        self._save(task)
        self._emit(task, "started")
        started = time.time()

        while True:
            if self._cancel[task_id].is_set():
                task["status"] = "cancelled"
                self._save(task)
                self._emit(task, "cancelled")
                return
            if self._pause[task_id].is_set():
                task["status"] = "paused"
                self._save(task)
                self._emit(task, "paused")
                return
            if time.time() - started > budget.get("max_seconds", 300):
                task["status"] = "failed"
                task["error"] = "任务超时"
                self._save(task)
                self._emit(task, "failed", "任务超时")
                return
            all_steps = task.get("steps", [])
            done = {s.get("id") for s in all_steps
                    if s.get("status") in ("done", "cancelled")}
            remaining = [s for s in all_steps
                         if s.get("status") not in ("done", "cancelled")]
            if not remaining:
                break
            if len(done) >= budget.get("max_steps", 8):
                task["status"] = "failed"
                task["error"] = "超过最大步骤预算"
                self._save(task)
                self._emit(task, "failed", task["error"])
                return
            ready = [s for s in remaining
                     if all(d in done for d in (s.get("deps") or []))]
            if not ready:
                task["status"] = "failed"
                task["error"] = "步骤依赖无法满足"
                self._save(task)
                self._emit(task, "failed", task["error"])
                return
            step = ready[0]
            if (step.get("tool")
                    and task["usage"].get("tool_calls", 0)
                    >= budget.get("max_tool_calls", 20)):
                task["status"] = "failed"
                task["error"] = "超过最大工具调用预算"
                self._save(task)
                self._emit(task, "failed", task["error"])
                return
            step["status"] = "running"
            step["started_at"] = time.time()
            self.trace.record({"kind": "step_started",
                               "task_id": task_id,
                               "step_id": step.get("id"),
                               "detail": step.get("title", "")})
            self._save(task)
            self._emit(task, "step_started", step.get("title", ""))
            r = self._exec_step(task, step)
            step["finished_at"] = time.time()
            step["result_preview"] = str(r)[:500]
            if step.get("tool"):
                task["usage"]["tool_calls"] = task["usage"].get("tool_calls", 0) + 1
            if isinstance(r, str):
                task["usage"]["tokens"] = task["usage"].get("tokens", 0) + max(1, len(r) // 4)
            elif isinstance(r, dict):
                metrics = r.get("metrics") or {}
                task["usage"]["tokens"] = task["usage"].get("tokens", 0) + int(
                    metrics.get("tokens", 0) or 0)
                task["usage"]["cost"] = round(
                    float(task["usage"].get("cost", 0.0))
                    + float(metrics.get("cost", 0.0) or 0.0), 6)
            if (budget.get("max_tokens")
                    and task["usage"].get("tokens", 0) > budget["max_tokens"]):
                task["status"] = "failed"
                task["error"] = "超过最大 token 预算"
                self._save(task)
                self._emit(task, "failed", task["error"])
                return
            if (budget.get("max_cost")
                    and task["usage"].get("cost", 0.0) > budget["max_cost"]):
                task["status"] = "failed"
                task["error"] = "超过最大费用预算"
                self._save(task)
                self._emit(task, "failed", task["error"])
                return
            if self._cancel[task_id].is_set():
                step["status"] = "cancelled"
                task["status"] = "cancelled"
                self._save(task)
                self._emit(task, "cancelled", step.get("title", ""))
                return
            if isinstance(r, dict) and r.get("ok") is False:
                step["status"] = "failed"
                step["error"] = str(r.get("错误") or r)[:300]
                task["status"] = "failed"
                task["error"] = step["error"]
                self._save(task)
                self._emit(task, "step_failed", step.get("title", ""))
                return
            step["status"] = "done"
            task["checkpoint"] = {"last_done": step.get("id")}
            self.trace.record({"kind": "step_done", "task_id": task_id,
                               "step_id": step.get("id"),
                               "detail": step.get("title", "")})
            self._save(task)
            self._emit(task, "step_done", step.get("title", ""))

        if self._cancel[task_id].is_set():
            task["status"] = "cancelled"
            self._save(task)
            self._emit(task, "cancelled")
            return
        task["status"] = "completed"
        task["final"] = "\n".join(
            str(s.get("result_preview", "")) for s in task.get("steps", []))
        self._save(task)
        self._emit(task, "completed")

        # M1-自学习：任务完成后自动捕获技能（待确认）
        try:
            sc = self.trunk.modules.get("skill_capture") if self.trunk else None
            if sc is None and self.trunk is not None:
                try:
                    sc = self.trunk._load_lazy("skill_capture")
                except Exception:
                    sc = None
            if sc and hasattr(sc, "capture"):
                r = sc.capture(
                    task=task.get("goal", ""),
                    result=task.get("final", ""),
                    success=True,
                    confirm=False,  # 待用户确认
                )
                # 把待确认技能名加到任务结果里，提示用户
                if isinstance(r, dict) and "待确认" in r:
                    pending_name = r["待确认"]
                    task["final"] = (task.get("final", "") +
                        "\n\n💡 这次做得不错？回复「确认 " + pending_name +
                        "」把它存成技能，以后自动用。")
                    self._save(task)
        except Exception as e:
            _x6_swallowed(__name__, e, "skill_capture auto capture")

    def _run_and_cleanup(self, task_id):
        try:
            self._run(task_id)
        except Exception as e:
            task = self.get_task(task_id)
            if task:
                task["status"] = "failed"
                task["error"] = "运行时异常: " + str(e)[:200]
                self._save(task)
                self._emit(task, "failed", task["error"])
        finally:
            with self._lock:
                self._threads.pop(task_id, None)

    def start(self, task_id):
        task = self.get_task(task_id)
        if not task:
            return {"ok": False, "错误": "任务不存在"}
        if not task.get("steps"):
            task = self.plan(task_id)
        if task.get("status") in ("running", "planning"):
            return {"ok": False, "错误": "任务已在运行"}
        with self._lock:
            old = self._threads.get(task_id)
            if old is not None and old.is_alive():
                return {"ok": False, "错误": "任务线程仍在运行"}
            th = threading.Thread(target=self._run_and_cleanup, args=(task_id,),
                                  daemon=True, name="task-" + task_id[-8:])
            self._threads[task_id] = th
        th.start()
        return {"ok": True, "task_id": task_id}

    def wait(self, task_id, timeout=60):
        th = self._threads.get(task_id)
        if th is not None:
            th.join(timeout=max(0.1, float(timeout)))
        return self.get_task(task_id)

    def run_sync(self, goal, *, timeout=60):
        """创建、计划并启动任务；超时则返回 task_id 让任务继续跑。"""
        task = self.create(goal)
        self.plan(task["id"])
        r = self.start(task["id"])
        if not r.get("ok"):
            return {"ok": False, "task_id": task["id"],
                    "错误": r.get("错误", "任务启动失败")}
        task = self.wait(task["id"], timeout)
        if task.get("status") == "completed":
            return {"ok": True, "task_id": task["id"],
                    "结果": task.get("final", "")}
        if task.get("status") in ("running", "paused", "pending"):
            return {"ok": True, "task_id": task["id"], "pending": True,
                    "结果": "任务已启动，可在任务中心查看进度（ID: %s）"
                            % task["id"]}
        return {"ok": False, "task_id": task["id"],
                "错误": task.get("error", task.get("status", "任务失败"))}

    def pause(self, task_id):
        if task_id not in self._pause:
            return {"ok": False, "错误": "任务未运行"}
        self._pause[task_id].set()
        return {"ok": True}

    def resume(self, task_id):
        task = self.get_task(task_id)
        if not task or task.get("status") not in ("paused", "failed"):
            return {"ok": False, "错误": "任务不可恢复"}
        for s in task.get("steps", []):
            if s.get("status") == "failed":
                s["status"] = "pending"
                s["error"] = ""
        task["status"] = "pending"
        self._save(task)
        return self.start(task_id)

    def cancel(self, task_id):
        if task_id in self._cancel:
            self._cancel[task_id].set()
        task = self.get_task(task_id)
        if task:
            for step in task.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "cancelled"
                    step["finished_at"] = time.time()
            task["status"] = "cancelled"
            self._save(task)
            self._emit(task, "cancelled")
        return {"ok": True}

    def retry_step(self, task_id, step_id):
        task = self.get_task(task_id)
        if not task:
            return {"ok": False, "错误": "任务不存在"}
        for s in task.get("steps", []):
            if s.get("id") == step_id:
                s["status"] = "pending"
                s["error"] = ""
                s["result_preview"] = ""
                task["status"] = "paused"
                self._save(task)
                return self.resume(task_id)
        return {"ok": False, "错误": "步骤不存在"}

    def increase_budget(self, task_id, *, seconds=120, steps=4, tokens=5000,
                        tool_calls=10):
        """任务超时 / 预算不足时，增加预算并保留已完成步骤。"""
        task = self.get_task(task_id)
        if not task:
            return {"ok": False, "错误": "任务不存在"}
        budget = task.setdefault("budget", {})
        budget["max_seconds"] = int(budget.get("max_seconds", 300)) + int(seconds)
        budget["max_steps"] = int(budget.get("max_steps", 8)) + int(steps)
        budget["max_tokens"] = int(budget.get("max_tokens", 20000)) + int(tokens)
        budget["max_tool_calls"] = int(
            budget.get("max_tool_calls", 20)) + int(tool_calls)
        self._save(task)
        self._emit(task, "budget_increased",
                   "seconds+%s steps+%s" % (seconds, steps))
        return {"ok": True, "task_id": task_id, "budget": budget}

    def approve_step(self, task_id, step_id, approved=True, scope="once"):
        return {"ok": bool(approved), "task_id": task_id,
                "step_id": step_id, "scope": scope}
