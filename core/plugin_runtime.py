# -*- coding: utf-8 -*-
"""插件运行时执行计划（功能深化二期 · F1 插件运行时）。

在"要不要隔离、缺哪些依赖"上给运行时一个统一决策，复用
``core.plugin_deps`` 的纯逻辑：

* 依赖缺失 -> 先补装，不启动；
* 高风险插件 -> 子进程沙箱（``mode="subprocess"``），否则主进程内（``mode="inproc"``）。

注意：本模块不改插件 API 版本常量（``PLUGIN_API_VERSION`` 仍是 1.0）。
"API v2" 需要同步改写 48 个清单与 ``modules.base``，属于独立迁移批次，
不在这里悄悄改常量，以免破坏清单一致性与既有测试。
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