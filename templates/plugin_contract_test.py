# -*- coding: utf-8 -*-
"""插件级契约测试模板（复制到你的插件 tests/ 目录后按需修改）。

用于验证插件是否**真正实现**了 manifest 里声明的东西。
对应小6插件标准 v2.1 N8.2(b)。
"""
import json

import pytest

PLUGIN_NAME = "your_plugin"
PLUGIN_CLS = None          # 填你的主类，例如 MyPlugin


@pytest.fixture
def plugin():
    return PLUGIN_CLS()


def test_entry_point_callable(plugin):
    assert callable(getattr(plugin, "run", None))


def test_declared_tools_exist(plugin, meta):
    missing = [t["method"] for t in meta.get("tools") or []
               if not callable(getattr(plugin, t.get("method"), None))]
    assert not missing


def test_lifecycle_idempotent(plugin):
    assert plugin.stop().get("ok") is True
    assert plugin.stop().get("already_stopped") is True


def test_output_is_json_serializable(plugin):
    json.dumps(plugin.stats(), ensure_ascii=False)


def test_error_is_structured(plugin):
    """错误必须返回 core.plugin_errors 结构，而不是纯字符串。"""
    from core.plugin_errors import is_error
    result = plugin.run()          # 按实际入参调整
    if isinstance(result, dict) and not result.get("ok", True):
        assert is_error(result) or "error" in result
