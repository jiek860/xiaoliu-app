# -*- coding: utf-8 -*-
"""系统自检「体检报告」（功能深化二期 · D4 系统自检）。

把一组检查结果聚合成可读的体检报告：每项 PASS/WARN/FAIL，整体取最差，
并统计三类各多少。纯逻辑，检查函数由调用方传入，便于测试与复用。

用法::

    report = build_report([
        ("模型", lambda: {"ok": True}),
        ("存储", lambda: {"ok": False, "hint": "磁盘不足"}),
    ])
    # report["overall"] == "fail"
"""
from __future__ import annotations

PASS = "pass"
WARN = "warn"
FAIL = "fail"


def status_from_ok(ok, warn=False):
    if not ok:
        return FAIL
    return WARN if warn else PASS


def overall_status(items):
    labels = [str((i or {}).get("status") or "") for i in (items or [])]
    if FAIL in labels:
        return FAIL
    if WARN in labels:
        return WARN
    return PASS


def summarize(items):
    items = [i for i in (items or []) if isinstance(i, dict)]
    pass_n = sum(1 for i in items if i.get("status") == PASS)
    warn_n = sum(1 for i in items if i.get("status") == WARN)
    fail_n = sum(1 for i in items if i.get("status") == FAIL)
    return {"overall": overall_status(items), "pass": pass_n,
            "warn": warn_n, "fail": fail_n, "items": items}


def build_report(checks):
    """checks: [(name, callable)], callable 返回 bool 或 {"ok","warn","hint"}。"""
    items = []
    for name, fn in checks or []:
        try:
            res = fn()
        except Exception as e:  # 单个检查崩了不能拖垮整份报告
            items.append({"name": str(name), "status": FAIL,
                          "hint": "检查异常: %s" % e})
            continue
        if isinstance(res, dict):
            ok = bool(res.get("ok", True))
            warn = bool(res.get("warn"))
            hint = str(res.get("hint") or res.get("reason") or "")
        else:
            ok, warn, hint = bool(res), False, ""
        items.append({"name": str(name), "status": status_from_ok(ok, warn),
                      "hint": hint})
    return summarize(items)