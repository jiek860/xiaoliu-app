# -*- coding: utf-8 -*-
"""代码 Agent 闭环测试（不调用真实模型）。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.agent_harness import reset_run_registry  # noqa: E402
from core.code_agent import CodeAgent  # noqa: E402


class FakeLLM:
    def __init__(self, patches):
        self.patches = list(patches)
        self.calls = 0

    def chat(self, messages):
        i = min(self.calls, len(self.patches) - 1)
        self.calls += 1
        return json.dumps(self.patches[i], ensure_ascii=False)


class FakeTrunk:
    allow_headless_agent = True

    def __init__(self, base, llm):
        self.base = base
        self.modules = {"llm": llm}


def _patch(old="value = 1", new="value = 2"):
    return {
        "goal": "改值",
        "files": [{
            "path": "m.py",
            "hunks": [{"old": old, "new": new, "reason": "测试"}],
        }],
    }


def test_code_agent_applies_patch_and_runs_tests(tmp_path):
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    trunk = FakeTrunk(str(root), FakeLLM([_patch()]))
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -c "print(123)"' % sys.executable])
    r = agent.run("把 value 改成 2", approved_cb=lambda p: True)
    assert r["ok"] is True, r
    assert "value = 2" in (root / "m.py").read_text(encoding="utf-8")
    assert r["tests"]["ok"] is True


def test_code_agent_failure_can_rollback(tmp_path, monkeypatch):
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    trunk = FakeTrunk(str(root), FakeLLM([_patch(), _patch("value = 2", "value = 3")]))
    agent = CodeAgent(trunk, str(root), test_commands=["does-not-run"])
    calls = {"n": 0}

    def fake_run_tests(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "results": [{"output": "fail", "ok": False}]}
        return {"ok": True, "results": [{"output": "ok", "ok": True}]}

    monkeypatch.setattr(agent, "run_tests", fake_run_tests)
    r = agent.run("修改并测试", approved_cb=lambda p: True)
    assert r["ok"] is True
    assert calls["n"] == 2
    assert "value = 3" in (root / "m.py").read_text(encoding="utf-8")
    rb = agent.rollback_all(r.get("backups") or [])
    assert rb["ok"] is True
    assert "value = 1" in (root / "m.py").read_text(encoding="utf-8")


def test_parse_test_failures_extracts_file_and_test():
    from core.code_agent import CodeAgent
    out = ('FAILED tests/test_a.py::test_x - AssertionError: boom\n'
           '  File "E:/p/m.py", line 12, in run\n'
           'AssertionError: bad')
    hits = CodeAgent.parse_test_failures(out)
    assert any(h["file"] == "tests/test_a.py" and h["test"] == "test_x"
               for h in hits)
    assert any(h["file"] == "E:/p/m.py" and h["line"] == 12 for h in hits)
