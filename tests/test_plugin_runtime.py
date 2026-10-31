# -*- coding: utf-8 -*-
"""F1 插件运行时执行计划 单元测试（功能深化二期）。"""
from core import plugin_runtime


def test_plan_ok_inproc():
    manifest = {"name": "demo", "capabilities": ["read_doc"], "risk": "low"}
    p = plugin_runtime.plan(manifest, lambda n: True)
    assert p["ok"] is True and p["isolate"] is False and p["mode"] == "inproc"


def test_plan_isolate_high_risk():
    p = plugin_runtime.plan({"risk": "high"}, lambda n: True)
    assert p["isolate"] is True and p["mode"] == "subprocess"


def test_plan_missing_deps():
    manifest = {"dependencies": ["dep1", "dep2"]}
    p = plugin_runtime.plan(manifest, lambda n: n == "dep1")
    assert p["ok"] is False
    assert p["missing"] == ["dep2"]
    assert p["needs_install"] == ["dep2"]


def test_plan_exec_capability_isolates():
    p = plugin_runtime.plan({"capabilities": ["exec_shell"]}, lambda n: True)
    assert p["isolate"] is True