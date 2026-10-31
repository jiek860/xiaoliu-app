# -*- coding: utf-8 -*-
"""插件运行时执行计划（功能深化二期 · F1 插件运行时）。

在"要不要隔离、缺哪些依赖"上给运行时一个统一决策，复用
``core.plugin_deps`` 的纯逻辑：

* 依赖缺失 -> 先补装，不启动；
* 高风险插件 -> 子进程沙箱（``mode="subprocess"``），否则主进程内（``mode="inproc"``）。

插件 API 版本已由独立迁移批次升到 2.0（``core.plugin_api``，v1.0 清单仍兼容）。
本模块只负责"依赖是否齐全 / 要不要隔离"的执行决策，不参与版本号判定。
"""
from __future__ import annotations

from core.plugin_deps import missing_deps, should_isolate


def plan(manifest, is_installed):
    """返回执行计划：{ok, missing, isolate, mode, needs_install}。"""
    manifest = manifest or {}
    missing = missing_deps(manifest, is_installed)
    isolate = should_isolate(manifest)
    return {
        "ok": not missing,
        "missing": missing,
        "isolate": isolate,
        "mode": "subprocess" if isolate else "inproc",
        "needs_install": list(missing),
    }