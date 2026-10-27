# -*- coding: utf-8 -*-
"""core/task_runtime.py 的同名测试：状态机、预算、持久化与幂等键。

全部在 tmp_path 下运行，不连网、不启动真实 Trunk。
"""
import json
import os
import time

import pytest

from core.task_runtime import TaskRuntime


class FakeLLM:
    def __init__(self, reply="ok", sleep=0.0):
        self.reply = reply
        self.sleep = sleep

    def chat(self, prompt):
        if self.sleep:
            time.sleep(self.sleep)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class FakeTrunk:
    def __init__(self, base, steps=None, llm=None):
        self.base = base
        self.config = {}
        self.modules = {}
        if llm is not None:
            self.modules["llm"] = llm
        self.steps = steps if steps is not None else [
            {"name": "第一步"},
            {"name": "第二步", "deps": ["第一步"]},
        ]
        self.calls = []

    def call(self, name, action, *args, **kwargs):
        self.calls.append((name, action) + args)
        if name == "task_planner" and action == "plan":
            return {"步骤": list(self.steps)}
        return {"ok": True}


class _Registry:
    def upsert_task(self, *a, **k):
        return None


@pytest.fixture(autouse=True)
def _no_run_registry(monkeypatch):
    monkeypatch.setattr("core.agent_harness.get_run_registry",
                        lambda: _Registry())


def _rt(tmp_path, **kw):
    return TaskRuntime(FakeTrunk(str(tmp_path), **kw))


def test_create_writes_task_file(tmp_path):
    rt = _rt(tmp_path)
    task = rt.create("整理桌面")
    assert task["status"] == "pending"
    assert task["goal"] == "整理桌面"
    p = os.path.join(rt.dir, task["id"] + ".json")
    assert os.path.isfile(p)
    assert json.load(open(p, encoding="utf-8"))["id"] == task["id"]


def test_plan_maps_dependency_names_to_step_ids(tmp_path):
    rt = _rt(tmp_path)
    task = rt.plan(rt.create("做两件事")["id"])
    assert [s["id"] for s in task["steps"]] == ["step_1", "step_2"]
    assert task["steps"][1]["deps"] == ["step_1"]


def test_plan_without_trunk_falls_back_to_one_step(tmp_path):
    rt = TaskRuntime(None)
    rt.base = str(tmp_path)
    rt.dir = os.path.join(str(tmp_path), "data", "task_runtime")
    os.makedirs(rt.dir, exist_ok=True)
    task = rt.plan(rt.create("无人计划")["id"])
    assert len(task["steps"]) == 1
    assert task["steps"][0]["title"] == "分析目标"


def test_get_task_returns_deep_copy(tmp_path):
    rt = _rt(tmp_path)
    t = rt.create("x")
    got = rt.get_task(t["id"])
    got["goal"] = "改掉"
    assert rt.get_task(t["id"])["goal"] == "x"


def test_list_tasks_newest_first(tmp_path):
    rt = _rt(tmp_path)
    a = rt.create("旧")
    time.sleep(0.01)
    b = rt.create("新")
    ids = [t["id"] for t in rt.list_tasks()]
    assert ids.index(b["id"]) < ids.index(a["id"])


def test_run_sync_completes_and_reports(tmp_path):
    rt = _rt(tmp_path, llm=FakeLLM("答复"))
    r = rt.run_sync("打个招呼", timeout=10)
    assert r["ok"] is True
    assert "答复" in r["结果"]
    assert rt.get_task(r["task_id"])["status"] == "completed"


def test_step_failure_marks_task_failed(tmp_path):
    rt = _rt(tmp_path, llm=FakeLLM(RuntimeError("模型挂了")))
    r = rt.run_sync("会失败", timeout=10)
    assert r["ok"] is False
    assert "模型挂了" in r["错误"]


def test_exec_step_without_llm_reports_error(tmp_path):
    rt = _rt(tmp_path)          # 没有 llm 模块
    task = rt.create("无模型")
    out = rt._exec_step(task, {"tool": "", "title": "分析"})
    assert out["ok"] is False and "LLM" in out["错误"]


def test_cancel_on_pending_task(tmp_path):
    rt = _rt(tmp_path)
    tid = rt.create("待取消")["id"]
    assert rt.cancel(tid)["ok"] is True
    assert rt.get_task(tid)["status"] == "cancelled"


def test_pause_rejects_non_running_task(tmp_path):
    rt = _rt(tmp_path)
    tid = rt.create("没在跑")["id"]
    assert rt.pause(tid) == {"ok": False, "错误": "任务未运行"}


def test_resume_rejects_completed_task(tmp_path):
    rt = _rt(tmp_path)
    task = rt.create("已完成")
    task["status"] = "completed"
    rt._save(task)
    assert rt.resume(task["id"])["ok"] is False


def test_retry_step_resets_and_resumes(tmp_path):
    rt = _rt(tmp_path, llm=FakeLLM("好"))
    task = rt.plan(rt.create("重试")["id"])
    step_id = task["steps"][0]["id"]
    task["steps"][0]["status"] = "failed"
    task["steps"][0]["error"] = "断了"
    rt._save(task)
    r = rt.retry_step(task["id"], step_id)
    assert r["ok"] is True
    rt.wait(task["id"], timeout=10)


def test_retry_step_missing_ids(tmp_path):
    rt = _rt(tmp_path)
    assert rt.retry_step("task_nope", "step_1")["ok"] is False
    tid = rt.plan(rt.create("x")["id"])["id"]
    assert rt.retry_step(tid, "step_99")["ok"] is False


def test_increase_budget_adds_each_dimension(tmp_path):
    rt = _rt(tmp_path)
    tid = rt.create("加预算")["id"]
    before = rt.get_task(tid)["budget"]
    r = rt.increase_budget(tid, seconds=60, steps=2, tokens=1000,
                           tool_calls=5)
    assert r["ok"] is True
    after = r["budget"]
    assert after["max_seconds"] == before["max_seconds"] + 60
    assert after["max_steps"] == before["max_steps"] + 2
    assert after["max_tokens"] == before["max_tokens"] + 1000
    assert after["max_tool_calls"] == before.get("max_tool_calls", 20) + 5


def test_increase_budget_missing_task(tmp_path):
    rt = _rt(tmp_path)
    assert rt.increase_budget("task_nope")["ok"] is False


def test_approve_step_echoes_scope(tmp_path):
    rt = _rt(tmp_path)
    r = rt.approve_step("t1", "step_1", approved=False, scope="always")
    assert r == {"ok": False, "task_id": "t1", "step_id": "step_1",
                 "scope": "always"}


def test_subscribe_receives_events(tmp_path):
    rt = _rt(tmp_path)
    seen = []
    rt.subscribe(lambda task, event, detail: seen.append(event))
    rt.create("订阅")
    assert "created" in seen


def test_unsubscribe_stops_events_and_reports_repeat(tmp_path):
    """对话框关闭必须能注销订阅，否则订阅列表只增不减。"""
    rt = _rt(tmp_path)
    seen = []
    cb = lambda *a: seen.append(a)        # noqa: E731
    rt.subscribe(cb)
    assert rt.unsubscribe(cb) is True
    assert rt.unsubscribe(cb) is False    # 第二次注销无事发生
    rt.create("没有订阅")
    assert seen == []


def test_plan_async_reports_done_from_worker(tmp_path):
    """拆步走后台线程；完成后回调 (task_id, ok)。"""
    rt = _rt(tmp_path)
    tid = rt.create("异步拆步")["id"]
    done = []
    th = rt.plan_async(tid, lambda t, ok: done.append((t, ok)))
    th.join(10)
    assert done == [(tid, True)]
    assert len(rt.get_task(tid)["steps"]) == 2


def test_plan_async_missing_task_reports_failure(tmp_path):
    rt = _rt(tmp_path)
    done = []
    rt.plan_async("task_nope", lambda t, ok: done.append((t, ok))).join(10)
    assert done == [("task_nope", False)]


def test_plan_async_survives_callback_error(tmp_path):
    """回调抛异常不能把拆步线程搞崩（也不影响任务本身）。"""
    rt = _rt(tmp_path)
    tid = rt.create("回调会炸")["id"]
    th = rt.plan_async(tid, lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    th.join(10)
    assert len(rt.get_task(tid)["steps"]) == 2


def test_idempotency_key_ignores_arg_order(tmp_path):
    rt = _rt(tmp_path)
    a = {"a": 1, "b": [2, 3]}
    b = {"b": [2, 3], "a": 1}
    assert rt._arg_hash(a) == rt._arg_hash(b)
    assert len(rt._arg_hash(a)) == 16
    key = rt._idem_key({"id": "t"}, {"id": "s", "tool": "x", "args": a})
    assert key.startswith("t:s:x:")


def test_tasks_survive_restart(tmp_path):
    rt = _rt(tmp_path)
    task = rt.create("重启还在")
    rt2 = TaskRuntime(FakeTrunk(str(tmp_path)))
    assert rt2.get_task(task["id"])["goal"] == "重启还在"


def test_created_event_emitted_with_step_plan(tmp_path):
    rt = _rt(tmp_path)
    tid = rt.create("先建后计划")["id"]
    task = rt.plan(tid)
    assert task["status"] == "pending"
    assert task["steps"][0]["status"] == "pending"
