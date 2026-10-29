# -*- coding: utf-8 -*-
"""批次 46.1：后台代码任务服务（单写者、取消、续跑、事件扇出）。"""
import os
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.agent_service import AgentService, get_agent_service  # noqa: E402
from core.code_task_queue import CodeTaskQueue  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}
        self.base = "."

    def rule(self, name, default=None):
        return self.rules.get(name, default)


def _service(tmp_path, runner, rules=None, timeout=600):
    return AgentService(FakeTrunk(rules), root=str(tmp_path),
                        queue=CodeTaskQueue(str(tmp_path)),
                        runner=runner, approval_timeout=timeout)


def _wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_submit_and_run_next(tmp_path):
    seen = []

    def runner(service, job):
        seen.append(job["goal"])
        service._emit("progress", {"step": "跑了一半"})
        return {"ok": True, "rounds_used": 1}

    service = _service(tmp_path, runner)
    events = []
    service.add_listener(lambda event, data: events.append(event))
    submitted = service.submit("修 bug")
    assert submitted["ok"] is True
    assert service.stats()["queued"] == 1
    result = service.run_next()
    assert result["ok"] is True
    assert seen == ["修 bug"]
    assert service.queue.get(submitted["job_id"])["status"] == "completed"
    assert {"queued", "job_start", "progress", "job_done"} <= set(events)
    assert service.busy() is False


def test_run_next_idle(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True})
    assert service.run_next() == {"ok": True, "idle": True}


def test_submit_annotates_mode_and_explicit(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True})
    submitted = service.submit("改一下", mode="L3", explicit="code",
                               selection="x = 1")
    job = service.queue.get(submitted["job_id"])
    assert job["mode"] == "L3"
    assert job["explicit"] == "code"
    assert job["selection"] == "x = 1"


def test_mode_falls_back_to_rule(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True},
                       rules={"code_agent.mode": "L1"})
    submitted = service.submit("改一下")
    assert service.queue.get(submitted["job_id"])["mode"] == "L1"


def test_single_writer_rejects_second_run(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def runner(service, job):
        started.set()
        release.wait(3)
        return {"ok": True}

    service = _service(tmp_path, runner)
    service.submit("任务一")
    first = {}
    thread = threading.Thread(target=lambda: first.update(service.run_next()))
    thread.start()
    assert started.wait(2)
    second = service.run_next()
    assert second.get("busy") is True
    release.set()
    thread.join(3)
    assert first.get("ok") is True


def test_cancel_active_job(tmp_path):
    started = threading.Event()

    def runner(service, job):
        started.set()
        for _ in range(300):
            if service._cancel.is_set():
                return {"ok": False, "cancelled": True, "error": "用户取消"}
            time.sleep(0.01)
        return {"ok": False}

    service = _service(tmp_path, runner)
    submitted = service.submit("长任务")
    thread = threading.Thread(target=service.run_next)
    thread.start()
    assert started.wait(2)
    assert service.cancel()["ok"] is True
    thread.join(4)
    assert service.queue.get(submitted["job_id"])["status"] == "paused"


def test_cancel_queued_job(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True})
    first = service.submit("一")
    second = service.submit("二")
    assert service.cancel(second["job_id"])["ok"] is True
    assert service.queue.get(second["job_id"])["status"] == "cancelled"
    service.run_next()
    assert service.queue.get(first["job_id"])["status"] == "completed"


def test_resume_cancelled_job(tmp_path):
    calls = {"n": 0}

    def runner(service, job):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "cancelled": True}
        return {"ok": True}

    service = _service(tmp_path, runner)
    submitted = service.submit("可续跑")
    service.run_next()
    assert service.queue.get(submitted["job_id"])["status"] == "paused"
    assert service.resume(submitted["job_id"])["ok"] is True
    assert service.queue.get(submitted["job_id"])["status"] == "queued"
    assert service.run_next()["ok"] is True
    assert service.queue.get(submitted["job_id"])["status"] == "completed"


def test_resume_rejects_unknown_or_finished(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True})
    assert service.resume("job_nope")["ok"] is False
    submitted = service.submit("跑完")
    service.run_next()
    assert service.resume(submitted["job_id"])["ok"] is False


def test_listener_failure_does_not_break_job(tmp_path):
    def bad_listener(event, data):
        raise RuntimeError("listener exploded")

    service = _service(tmp_path, lambda s, j: {"ok": True})
    service.add_listener(bad_listener)
    service.submit("任务")
    assert service.run_next()["ok"] is True


def test_remove_listener_and_stats(tmp_path):
    service = _service(tmp_path, lambda s, j: {"ok": True})
    listener = lambda event, data: None  # noqa: E731
    assert service.add_listener(listener) is True
    assert service.stats()["listeners"] == 1
    assert service.remove_listener(listener) is True
    assert service.stats()["listeners"] == 0
    assert service.add_listener("not callable") is False


def test_get_agent_service_reuses_instance(tmp_path):
    first = get_agent_service(FakeTrunk(), root=str(tmp_path), runner=lambda s, j: {})
    second = get_agent_service(FakeTrunk(), root=str(tmp_path))
    assert first is second
    first.close()
