# -*- coding: utf-8 -*-
"""模块调用统计（功能深化二期 · D5 模块星图）。

轻量、线程安全的调用计数：模块/方法被调用多少次、平均耗时、出错次数。
星图据此给"高频/慢/出错"上色，日志/自检也能复用。

不依赖 trunk：trunk 可在每次 call 时调用 ``record()``，UI 侧用
``snapshot()/hot()/slow()/erroring()`` 取数据。
"""
from __future__ import annotations

import threading


class CallStats:
    def __init__(self):
        self._data = {}
        self._lock = threading.RLock()

    def record(self, module, method, dur_ms=0.0, error=False):
        key = "%s.%s" % (str(module or ""), str(method or ""))
        with self._lock:
            rec = self._data.setdefault(
                key, {"key": key, "count": 0, "total_ms": 0.0, "errors": 0})
            rec["count"] += 1
            rec["total_ms"] += max(0.0, float(dur_ms or 0.0))
            if error:
                rec["errors"] += 1
            return dict(rec)

    def snapshot(self):
        with self._lock:
            out = []
            for rec in self._data.values():
                r = dict(rec)
                r["total_ms"] = round(r["total_ms"], 2)
                r["avg_ms"] = round(r["total_ms"] / r["count"], 2) if r["count"] else 0.0
                r["error_rate"] = round(r["errors"] / r["count"], 3) if r["count"] else 0.0
                out.append(r)
            return out

    def hot(self, n=10):
        return sorted(self.snapshot(), key=lambda r: r["count"], reverse=True)[:max(1, n)]

    def slow(self, n=10):
        return sorted(self.snapshot(), key=lambda r: r["avg_ms"], reverse=True)[:max(1, n)]

    def erroring(self, n=10):
        return sorted(self.snapshot(), key=lambda r: r["error_rate"], reverse=True)[:max(1, n)]

    def reset(self):
        with self._lock:
            self._data.clear()


_STATS = CallStats()


def stats():
    return _STATS


def record(module, method, dur_ms=0.0, error=False):
    return _STATS.record(module, method, dur_ms, error)