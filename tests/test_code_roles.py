# -*- coding: utf-8 -*-
"""双角色 Agent：探索 -> 报告 -> 修改，以及退回单角色。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code_agent import CodeAgent  # noqa: E402
from core.code_roles import two_role_enabled  # noqa: E402


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages):
        i = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        return json.dumps(self.replies[i], ensure_ascii=False)


class Trunk:
    allow_headless_agent = True
    config = {}

    def __init__(self, base, llm):
        self.base = base
        self.modules = {"llm": llm}


def _patch(new="value = 2"):
    return {"goal": "改值", "files": [{
        "path": "m.py", "hunks": [{"old": "value = 1", "new": new}]}]}


def _agent(tmp_path, llm, config=None):
    root = tmp_path / "p"
    root.mkdir(exist_ok=True)
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    trunk = Trunk(str(root), llm)
    if config:
        trunk.config = config
    return CodeAgent(trunk, str(root))


def test_two_role_flag_env_and_config(monkeypatch):
    t = Trunk(".", None)
    assert two_role_enabled(t) is True
    t.config = {"code_agent": {"two_role": False}}
    assert two_role_enabled(t) is False
    t.config = {}
    monkeypatch.setenv("X6_CODE_AGENT_TWO_ROLE", "0")
    assert two_role_enabled(t) is False


def test_explore_then_modify(tmp_path, monkeypatch):
    llm = FakeLLM([
        {"tool": "find_symbols", "args": {"query": "value"}},
        {"report": "m.py 里 value=1，改这一行即可"},
        _patch(),
    ])
    agent = _agent(tmp_path, llm)
    seen = []
    monkeypatch.setattr(agent, "_tool_result",
                        lambda name, args: seen.append(name) or {"ok": True})
    patch = agent.propose_patch("把 value 改成 2")
    assert seen == ["find_symbols"]
    assert patch["files"][0]["path"] == "m.py"
    assert llm.calls == 3


def test_explore_direct_patch_skips_modifier(tmp_path):
    llm = FakeLLM([_patch()])
    agent = _agent(tmp_path, llm)
    patch = agent.propose_patch("改值")
    assert patch["files"][0]["hunks"][0]["new"] == "value = 2"
    assert llm.calls == 1


def test_single_role_fallback(tmp_path):
    llm = FakeLLM([_patch()])
    agent = _agent(tmp_path, llm, config={"code_agent": {"two_role": False}})
    patch = agent.propose_patch("改值")
    assert patch["files"][0]["path"] == "m.py"
    assert llm.calls == 1
