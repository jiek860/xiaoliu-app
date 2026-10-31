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


def test_trunk_call_records_stats(tmp_path):
    """trunk.call 是统一入口：每次真实调用都要进统计（星图/自检看的就是它）。"""
    from core import call_stats
    from core.trunk_registry import TrunkRegistryMixin

    class _Demo:
        def ok(self):
            return {"ok": True}

        def boom(self):
            raise RuntimeError("boom")

    class FakeTrunk(TrunkRegistryMixin):
        def __init__(self):
            self.base = str(tmp_path)
            self.modules = {"demo": _Demo()}
            self._lazy = {}
            self._aliases = {}
            self._last_use = {}
            self.config = {}
            self.module_meta = {}

        def _log(self, *a, **k):
            pass

    t = FakeTrunk()
    call_stats.stats().reset()
    try:
        assert t.call("demo", "ok") == {"ok": True}
        assert t.call("demo", "boom")["ok"] is False
        snap = {r["key"]: r for r in call_stats.stats().snapshot()}
        assert snap["demo.ok"]["count"] == 1
        assert snap["demo.ok"]["errors"] == 0
        assert snap["demo.boom"]["errors"] == 1
    finally:
        call_stats.stats().reset()


def test_module_map_carries_runtime(tmp_path):
    """星图节点要带运行态（调用次数/平均耗时/错误率），否则接线等于没接。"""
    from core import call_stats, module_map

    class T:
        base = str(tmp_path)
        modules = {"demo": object()}
        _lazy = {}

    call_stats.stats().reset()
    try:
        call_stats.record("demo", "x", 10)
        call_stats.record("demo", "y", 30, error=True)
        data = module_map.build(T())
        node = [m for m in data["modules"] if m["name"] == "demo"][0]
        assert node["calls"] == 2
        assert node["avg_ms"] == 20.0
        assert node["error_rate"] == 0.5
        assert data["runtime"]["demo"]["count"] == 2
    finally:
        call_stats.stats().reset()