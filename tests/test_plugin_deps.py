# -*- coding: utf-8 -*-
"""D1/F1 插件依赖解析 + 隔离策略 单元测试（功能深化二期）。"""
from core import plugin_deps


def test_parse_version():
    assert plugin_deps.parse_version("v1.2.3") == (1, 2, 3)
    assert plugin_deps.parse_version("1.2") == (1, 2, 0)
    assert plugin_deps.parse_version("1") == (1, 0, 0)
    assert plugin_deps.parse_version("") == (0, 0, 0)
    assert plugin_deps.parse_version("垃圾") == (0, 0, 0)


def test_newer():
    assert plugin_deps.newer("1.3.0", "1.2.9") is True
    assert plugin_deps.newer("1.2.0", "1.2.0") is False
    assert plugin_deps.newer("1.0.0", "2.0.0") is False


def test_missing_deps():
    manifest = {"dependencies": ["a", {"name": "b"}, "", {"id": "c"}]}
    installed = {"a": True, "c": True}
    missing = plugin_deps.missing_deps(
        manifest, lambda n: installed.get(n, False))
    assert missing == ["b"]


def test_missing_deps_none():
    assert plugin_deps.missing_deps({}, lambda n: True) == []


def test_should_isolate_by_risk():
    assert plugin_deps.should_isolate({"risk": "high"}) is True
    assert plugin_deps.should_isolate({"risk": "low"}) is False


def test_should_isolate_by_capability():
    assert plugin_deps.should_isolate({"capabilities": ["exec_shell"]}) is True
    assert plugin_deps.should_isolate({"capabilities": ["read_doc"]}) is False
    assert plugin_deps.should_isolate({}) is False