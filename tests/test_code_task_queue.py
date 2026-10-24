# -*- coding: utf-8 -*-
"""代码任务队列：入队、断点、崩溃恢复与状态流转。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code_task_queue import CodeTaskQueue, get_code_queue  # noqa: E402


def test_enqueue_checkpoint_and_resume(tmp_path):
    q = CodeTaskQueue(str(tmp_path))
    job = q.enqueue("修 bug", max_rounds=12)
    assert job["status"] == "queued"
    q.mark_running(job["job_id"])
    q.checkpoint(job["job_id"], {
        "round": 4, "last_error": "E assert", "fingerprints": ["aa"],
        "patches": ["p1"], "backups": ["m1"], "done": False})
    got = q.get(job["job_id"])
    assert got["status"] == "running" and got["round"] == 4
    state = q.checkpoint_of(got)
    assert state["last_error"] == "E assert"
    assert q.resumable() == []  # running 不算可续跑

    # 模拟进程崩溃：重新加载 -> running 变 interrupted
    q2 = CodeTaskQueue(str(tmp_path))
    got2 = q2.get(job["job_id"])
    assert got2["status"] == "interrupted"
    assert [j["job_id"] for j in q2.resumable()] == [job["job_id"]]


def test_mark_done_and_failed(tmp_path):
    q = CodeTaskQueue(str(tmp_path))
    j1 = q.enqueue("ok")
    q.mark_done(j1["job_id"], {"ok": True, "rounds_used": 2,
                               "stop_reason": "tests_green"})
    j2 = q.enqueue("bad")
    q.mark_done(j2["job_id"], {"ok": False, "error": "boom",
                               "stop_reason": "no_progress"})
    assert q.get(j1["job_id"])["status"] == "completed"
    assert q.get(j2["job_id"])["status"] == "failed"
    assert q.get(j2["job_id"])["stop_reason"] == "no_progress"
    q.remove_finished()
    assert q.jobs() == []


def test_queue_persists_and_reuses_instance(tmp_path):
    q = get_code_queue(str(tmp_path))
    j = q.enqueue("持久化")
    raw = json.loads(open(os.path.join(str(tmp_path), "data", "code_jobs",
                                       "queue.json"), encoding="utf-8").read())
    assert raw["jobs"][0]["job_id"] == j["job_id"]
    assert get_code_queue(str(tmp_path)) is q
