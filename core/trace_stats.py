# -*- coding: utf-8 -*-
"""Trace 事件统计（功能深化二期 · D3 Trace 回看）。

纯函数，输入是 ``Trace.read()`` 返回的事件列表（dict），输出：

* ``slowest``：最耗时 Top N（用于"瓶颈定位"）；
* ``failures``：失败事件（给失败链路标红用）；
* ``aggregate``：按组件聚合次数/总耗时/失败数（星图与火焰图的数据源）；
* ``summary``：整体概览（总数/失败数/总耗时/最慢几条）。

事件对形状很宽容：耗时优先取 ``dur_ms``/``duration_ms``/``elapsed_ms``，
其次用 ``end - start``，取不到就记 0。
"""
from __future__ import annotations

_FAIL_STATUS = ("error", "fail", "failed", "failure", "失败", "错误", "异常")


def dur_ms(ev):
    for k in ("dur_ms", "duration_ms", "elapsed_ms"):
        v = ev.get(k)
        if isinstance(v, (int, float)):
            return max(0.0, float(v))
    if ev.get("start") is not None and ev.get("end") is not None:
        try:
            return max(0.0, float(ev["end"]) - float(ev["start"]))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _component(ev):
    # 真实事件（core/task_runtime.py 写的）用的是 kind：step_started / step_failed…
    # 没有 kind 时再退回 component/module/name/event，避免统计里全是 "unknown"。
    return str(ev.get("component") or ev.get("module") or ev.get("name")
               or ev.get("kind") or ev.get("event") or "")


def _is_failure(ev):
    if ev.get("ok") is False:
        return True
    status = str(ev.get("status") or "").strip().lower()
    if status in _FAIL_STATUS:
        return True
    # 步骤事件没有 ok 字段，失败只体现在 kind/event 名字上（step_failed）
    kind = str(ev.get("kind") or ev.get("event") or "").strip().lower()
    return any(k in kind for k in ("fail", "error", "失败", "错误", "异常"))


def slowest(events, n=5):
    rows = sorted(events or [], key=dur_ms, reverse=True)[:max(1, int(n))]
    return [{"component": _component(e), "dur_ms": round(dur_ms(e), 2)}
            for e in rows if dur_ms(e) > 0]


def failures(events):
    return [e for e in (events or []) if _is_failure(e)]


def aggregate(events, n=10):
    """按组件聚合：次数 / 总耗时 / 平均 / 失败数，按总耗时倒序。"""
    groups = {}
    for e in events or []:
        key = _component(e) or "unknown"
        g = groups.setdefault(key, {"component": key, "count": 0,
                                    "total_ms": 0.0, "errors": 0})
        g["count"] += 1
        g["total_ms"] += dur_ms(e)
        if _is_failure(e):
            g["errors"] += 1
    rows = []
    for g in groups.values():
        g["total_ms"] = round(g["total_ms"], 2)
        g["avg_ms"] = round(g["total_ms"] / g["count"], 2) if g["count"] else 0.0
        rows.append(g)
    rows.sort(key=lambda x: x["total_ms"], reverse=True)
    return rows[:max(1, int(n))]


def summary(events, n=5):
    events = events or []
    fails = failures(events)
    return {
        "count": len(events),
        "failures": len(fails),
        "total_ms": round(sum(dur_ms(e) for e in events), 2),
        "slowest": slowest(events, n),
        "top_components": aggregate(events, n),
    }