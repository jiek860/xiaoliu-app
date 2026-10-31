# -*- coding: utf-8 -*-
"""D5 模块调用统计 单元测试（功能深化二期）。"""
from core.call_stats import CallStats


def test_record_and_snapshot():
    cs = CallStats()
    cs.record("m", "x", dur_ms=10)
    cs.record("m", "x", dur_ms=30)
    snap = cs.snapshot()
    assert len(snap) == 1
    r = snap[0]
    assert r["count"] == 2 and r["total_ms"] == 40.0 and r["avg_ms"] == 20.0


def test_hot_slow_erroring():
    cs = CallStats()
    for _ in range(5):
        cs.record("a", "hot", dur_ms=1)
    for _ in range(2):
        cs.record("b", "slow", dur_ms=100)
    cs.record("c", "err", dur_ms=1, error=True)
    cs.record("c", "err", dur_ms=1, error=True)
    assert cs.hot(1)[0]["key"] == "a.hot"
    assert cs.slow(1)[0]["key"] == "b.slow"
    assert cs.erroring(1)[0]["key"] == "c.err"
    assert cs.erroring(1)[0]["error_rate"] == 1.0


def test_reset():
    cs = CallStats()
    cs.record("m", "x")
    cs.reset()
    assert cs.snapshot() == []