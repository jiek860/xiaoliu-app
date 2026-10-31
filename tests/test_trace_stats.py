# -*- coding: utf-8 -*-
"""D3 Trace 统计 单元测试（功能深化二期）。"""
from core import trace_stats
from core.trace import Trace


def _ev(**kw):
    return dict(kw)


def test_dur_ms_variants():
    assert trace_stats.dur_ms({"dur_ms": 12.5}) == 12.5
    assert trace_stats.dur_ms({"start": 1.0, "end": 2.0}) == 1.0
    assert trace_stats.dur_ms({"dur_ms": -5}) == 0.0
    assert trace_stats.dur_ms({}) == 0.0


def test_slowest_and_failures():
    events = [
        _ev(component="a", dur_ms=10),
        _ev(component="b", dur_ms=50),
        _ev(component="c", dur_ms=5, ok=False),
    ]
    slow = trace_stats.slowest(events, 2)
    assert [s["component"] for s in slow] == ["b", "a"]
    fails = trace_stats.failures(events)
    assert len(fails) == 1 and fails[0]["component"] == "c"


def test_aggregate_by_component():
    events = [
        _ev(component="a", dur_ms=10),
        _ev(component="a", dur_ms=20),
        _ev(component="a", dur_ms=30, ok=False),
        _ev(component="b", dur_ms=5),
    ]
    agg = trace_stats.aggregate(events)
    assert agg[0]["component"] == "a"
    assert agg[0]["count"] == 3
    assert agg[0]["errors"] == 1


def test_summary_shape():
    events = [_ev(component="a", dur_ms=10), _ev(component="b", dur_ms=5, ok=False)]
    s = trace_stats.summary(events)
    assert s["count"] == 2 and s["failures"] == 1
    assert s["total_ms"] == 15.0


def test_trace_span_records_duration(tmp_path):
    tr = Trace(str(tmp_path))
    with tr.span("demo", note="x"):
        pass
    events = tr.read()
    assert events and events[-1]["component"] == "demo"
    assert events[-1]["ok"] is True
    assert events[-1]["dur_ms"] >= 0
    assert tr.summary()["count"] >= 1


def test_real_task_events_use_kind():
    """真实事件（task_runtime 写的）只有 kind，没有 ok/component。"""
    events = [
        {"kind": "step_started", "task_id": "t", "status": "running"},
        {"kind": "step_failed", "task_id": "t", "status": "failed"},
        {"kind": "step_done", "task_id": "t", "status": "completed"},
    ]
    s = trace_stats.summary(events)
    assert s["count"] == 3 and s["failures"] == 1
    assert trace_stats.failures(events)[0]["kind"] == "step_failed"
    slow = trace_stats.slowest([{"kind": "tool_call", "dur_ms": 80}], 1)
    assert slow[0]["component"] == "tool_call"