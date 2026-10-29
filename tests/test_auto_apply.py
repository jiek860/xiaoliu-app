# -*- coding: utf-8 -*-
"""批次 46.2：L2/L3 自动档与审批代理（低风险自动、高风险问人）。"""
import os
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.agent_service import AgentService  # noqa: E402
from core.code_task_queue import CodeTaskQueue  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}

    def rule(self, name, default=None):
        return self.rules.get(name, default)


def _service(tmp_path, rules=None, timeout=5):
    return AgentService(FakeTrunk(rules), root=str(tmp_path),
                        queue=CodeTaskQueue(str(tmp_path)),
                        runner=lambda s, j: {"ok": True},
                        approval_timeout=timeout)


def _low_patch():
    return {"files": [{"op": "create", "path": "new.py", "content": "x = 1\n"}]}


def _high_patch():
    return {"files": [{"op": "delete", "path": "old.py"}]}


def _wait_event(events, name, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if any(e == name for e, _ in events):
            return True
        time.sleep(0.01)
    return False


def _ask_in_thread(service, job, kind="code", patch=None):
    holder = {}

    def run():
        holder["ok"] = service._approve(job, kind, patch or _low_patch())

    thread = threading.Thread(target=run)
    thread.start()
    return thread, holder


def test_low_risk_auto_applied_in_l2(tmp_path):
    service = _service(tmp_path, {"code_agent.auto_apply": True})
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    assert service._approve({"mode": "L2"}, "code", _low_patch()) is True
    assert any(e == "auto_apply" for e, _ in events)


def test_medium_risk_auto_applied_in_l2(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    patch = {"files": [{"op": "update", "path": "m.py",
                        "hunks": [{"old": "value = 1", "new": "value = 2"}]}]}
    service = _service(tmp_path, {"code_agent.auto_apply": True})
    assert service._approve({"mode": "L2"}, "code", patch) is True


def test_high_risk_asks_user_in_l2(tmp_path):
    service = _service(tmp_path, {"code_agent.auto_apply": True})
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    thread, holder = _ask_in_thread(service, {"mode": "L2"}, patch=_high_patch())
    assert _wait_event(events, "approval_required")
    assert _wait_event(events, "approval")
    request_id = [d["request_id"] for e, d in events if e == "approval"][0]
    assert service.answer(request_id, True) is True
    thread.join(3)
    assert holder["ok"] is True


def test_high_risk_auto_applied_in_l3(tmp_path):
    service = _service(tmp_path, {"code_agent.auto_apply": True})
    assert service._approve({"mode": "L3"}, "code", _high_patch()) is True


def test_auto_apply_off_always_asks(tmp_path):
    service = _service(tmp_path, {})
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    thread, holder = _ask_in_thread(service, {"mode": "L2"}, patch=_low_patch())
    assert _wait_event(events, "approval")
    request_id = [d["request_id"] for e, d in events if e == "approval"][0]
    service.answer(request_id, False)
    thread.join(3)
    assert holder["ok"] is False


def test_l1_never_auto_applies(tmp_path):
    service = _service(tmp_path, {"code_agent.auto_apply": True})
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    thread, holder = _ask_in_thread(service, {"mode": "L1"}, patch=_low_patch())
    assert _wait_event(events, "approval")
    request_id = [d["request_id"] for e, d in events if e == "approval"][0]
    service.answer(request_id, False)
    thread.join(3)
    assert holder["ok"] is False


def test_approval_timeout_is_denied(tmp_path):
    service = _service(tmp_path, {}, timeout=1)
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    thread, holder = _ask_in_thread(service, {"mode": "L2"})
    thread.join(4)
    assert holder["ok"] is False
    assert any(e == "approval_timeout" for e, _ in events)


def test_answer_unknown_request_returns_false(tmp_path):
    service = _service(tmp_path)
    assert service.answer("approval_missing", True) is False


def test_cancel_releases_pending_approval(tmp_path):
    service = _service(tmp_path, {}, timeout=30)
    events = []
    service.add_listener(lambda e, d: events.append((e, d)))
    thread, holder = _ask_in_thread(service, {"mode": "L2"})
    assert _wait_event(events, "approval")
    service.cancel()
    thread.join(3)
    assert holder["ok"] is False
