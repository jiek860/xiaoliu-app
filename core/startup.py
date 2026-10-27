# -*- coding: utf-8 -*-
"""Startup timing recorder.

Every mark is milliseconds since process start, so ``python -c "import core.startup;
from core.startup import report; print(report())"`` or the GUI can show where the
time went. It must stay dependency-free and import in well under a millisecond.
"""
from __future__ import annotations

import os
import sys
import time

_T0 = time.perf_counter()
_MARKS = []
_WALL0 = time.time()


def mark(name):
    """记录一个阶段（任意线程可调用）。"""
    # 不用 try/except：列表 append 不会失败，异常只会让计时器"看起来在工作"
    _MARKS.append((str(name), (time.perf_counter() - _T0) * 1000.0))
    return _MARKS[-1][1]


def since_start_ms():
    return (time.perf_counter() - _T0) * 1000.0


def elapsed_ms(name, start_ms):
    """Milliseconds since ``start_ms`` and record ``name``."""
    now = since_start_ms()
    _MARKS.append((str(name), now))
    return now - float(start_ms or 0.0)


def report():
    """Return ordered marks, total elapsed and the per-stage deltas."""
    total = since_start_ms()
    stages = []
    prev = 0.0
    for name, at in _MARKS:
        stages.append({"name": name, "at_ms": round(at, 1),
                       "delta_ms": round(at - prev, 1)})
        prev = at
    return {"total_ms": round(total, 1), "stages": stages,
            "pid": os.getpid(), "frozen": bool(getattr(sys, "frozen", False)),
            "started_at": _WALL0}


def log_summary(trunk=None):
    """Write the current report to the trunk log (never raises)."""
    try:
        data = report()
        parts = ["%s=%.0fms" % (s["name"], s["at_ms"]) for s in data["stages"]]
        line = "[启动耗时] 总 %.0f ms | %s" % (data["total_ms"], " → ".join(parts))
        if trunk is not None:
            # 顺手把总耗时挂到躯干上：深度自检读它报"🚀 启动耗时"。
            # 以前自检读的是 trunk._boot_time —— 那个属性根本不存在
            # （它属于 scheduler 模块），所以那行从来没打印过。
            try:
                trunk._boot_ms = data["total_ms"]
            # 静默是故意的：只做“顺手上报耗时”，躯干属性可能只读或没有
            # __dict__；写不进去也不该影响启动或日志。
            except Exception:
                pass
            if hasattr(trunk, "_log"):
                trunk._log(line)
        return line
    except Exception:
        return ""
