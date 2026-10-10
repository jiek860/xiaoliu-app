# -*- coding: utf-8 -*-
"""微核契约：trunk.call 的行为

注意用 quiet_trunk 造 Trunk —— 直接 Trunk() 的话，3 秒后 _start_background
会在后台起服务、连你配置里的 MCP 服务器（拉起 npx / uvx 子进程）、
跑 ollama 预热和自动备份。测试不该干这些（见 tests/conftest.py）。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def test_trunk_call_missing(quiet_trunk):
    t = quiet_trunk()
    r = t.call("__not_exist__", "run")
    assert isinstance(r, dict)
    assert r.get("ok") is False


def test_trunk_call_missing_method(quiet_trunk):
    """模块在、方法不在，也要给出可读的失败而不是抛异常

    探针名用双下划线形式 —— 这是本项目里"故意调不存在的方法"的约定，
    tools/check_shapes.py 会认出来并跳过（否则它会被当成真的拼写错误）。
    """
    t = quiet_trunk()
    r = t.call("vector_store", "__no_such_method__")
    assert isinstance(r, dict)
    assert r.get("ok") is False


def test_quiet_trunk_does_not_start_background(quiet_trunk):
    """守住本文件的前提：后台服务确实是关着的"""
    t = quiet_trunk()
    assert getattr(t, "_module_server", None) is None
    assert t.modules.get("mcp_server") is None or \
        not getattr(t.modules.get("mcp_server"), "_http_server", None)
