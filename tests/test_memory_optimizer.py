# -*- coding: utf-8 -*-
"""memory_optimizer 完整版测试：清理计数 / 弱引用 / 定期线程幂等"""
import gc
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.memory_optimizer import MemoryOptimizer     # noqa: E402


def test_cleanup_counts_and_stats():
    mo = MemoryOptimizer()
    before = mo.stats()["清理次数"]
    r = mo.cleanup()
    assert r["ok"] and r["清理次数"] == before + 1
    st = mo.stats()
    assert st["清理次数"] == before + 1
    assert st["上次清理"] > 0


def test_register_weak_allows_collection():
    mo = MemoryOptimizer()

    class X:
        pass

    x = X()
    mo.register_weak("x", x)
    assert mo.stats()["弱引用模块数"] == 1
    del x
    gc.collect()
    assert mo.stats()["弱引用模块数"] == 0


def test_start_periodic_is_idempotent():
    mo = MemoryOptimizer()
    first = mo.start_periodic(3600)
    assert first["状态"] == "已启动"
    t = mo._thread
    second = mo.start_periodic(3600)
    assert second["状态"] == "已在运行"
    assert mo._thread is t                      # 没有另起线程
    assert mo.stats()["定期线程存活"] is True


def test_tune_gc_returns_ok():
    assert MemoryOptimizer().tune_gc()["ok"] is True
