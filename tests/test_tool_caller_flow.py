# -*- coding: utf-8 -*-
"""ToolCaller end-to-end flow with a fake LLM and fake modules."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.untrusted_content import external_provenance  # noqa: E402
from modules.installed.tool_caller import ToolCaller  # noqa: E402


class _LLM:
    def __init__(self, payload):
        self.payload = payload

    def chat(self, _prompt):
        return self.payload


class _Search:
    def search(self, query):
        return "result:" + query


class _Logger:
    def __init__(self):
        self.calls = []

    def log_call(self, *args):
        self.calls.append(args)


class _FakeTrunk:
    def __init__(self, llm_payload):
        self.base = BASE
        self.config = {}
        self.modules = {
            "llm": _LLM(llm_payload),
            "deep_search": _Search(),
            "tool_call_logger": _Logger(),
        }
        self.confirm_cb = lambda *_a: True

    def rule(self, _key, default=False):
        return True

    def call(self, mod, method, *args, **kwargs):
        target = self.modules.get(mod)
        if target is None:
            raise KeyError(mod)
        if method == "__no__":
            return None
        return getattr(target, method)(*args, **kwargs)

    def _log(self, *_a, **_k):
        pass


def test_call_tools_real_dispatch_flow():
    trunk = _FakeTrunk('[{"tool": "deep_search", "args": {"query": "x"}}]')
    caller = ToolCaller(trunk)
    result = caller.call_tools("search something")
    assert result["用工具"] == ["deep_search"]
    assert result["结果"][0]["成功"] is True
    assert trunk.modules["tool_call_logger"].calls


def test_call_tools_no_tool_branch():
    trunk = _FakeTrunk("[]")
    caller = ToolCaller(trunk)
    assert caller.call_tools("hello") == {"用工具": "无", "回答": "直接聊天"}


def test_call_tools_untrusted_mcp_is_denied():
    trunk = _FakeTrunk('[{"tool": "mcp_echo", "args": {"input": "x"}}]')
    caller = ToolCaller(trunk)
    caller.tools["mcp_echo"] = {
        "desc": "mcp", "mod": "mcp_server", "method": "call_tool",
        "args": {"input": "x"}, "mcp_name": "echo",
        "confirm": True, "risk": "mcp_external",
    }
    result = caller.call_tools(
        "external prompt", provenance=external_provenance("web"))
    assert result["结果"][0]["成功"] is False
    assert "外部内容" in result["结果"][0]["结果"]


def test_llm_decide_invalid_json_falls_back_empty():
    trunk = _FakeTrunk("not json")
    caller = ToolCaller(trunk)
    assert caller._llm_decide("query") == []


def test_run_returns_usage_stats():
    trunk = _FakeTrunk("[]")
    caller = ToolCaller(trunk)
    caller.usage_history = [{"ok": True}, {"ok": False}]
    stats = caller.run()
    assert stats["总调用"] == 2
    assert stats["成功率"] == "50%"


def test_external_tool_result_is_wrapped_for_model():
    trunk = _FakeTrunk('[{"tool": "deep_search", "args": {"query": "x"}}]')
    caller = ToolCaller(trunk)
    result = caller.call_tools("search something")
    text = result["结果"][0]["结果"]
    assert "<<<UNTRUSTED_EXTERNAL_CONTENT" in text
    assert "result:x" in text


def test_plugin_tool_result_is_wrapped_for_model():
    trunk = _FakeTrunk('[{"tool": "plugin_note", "args": {"text": "x"}}]')
    caller = ToolCaller(trunk)
    trunk.modules["notes"] = type("Notes", (), {
        "run": lambda self, text="": "plugin says " + text})()
    caller.tools["plugin_note"] = {
        "desc": "plugin note", "mod": "notes", "method": "run",
        "args": {"text": "x"}, "readonly": True, "source": "plugin",
    }
    result = caller.call_tools("run plugin")
    text = result["结果"][0]["结果"]
    assert "<<<UNTRUSTED_EXTERNAL_CONTENT" in text
