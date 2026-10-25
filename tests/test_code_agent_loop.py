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
        self.messages = []

    def chat(self, messages):
        self.messages.append(list(messages))
        i = min(self.calls, len(self.patches) - 1)
        self.calls += 1
        return json.dumps(self.patches[i], ensure_ascii=False)


class FakeTrunk:
    allow_headless_agent = True
    config = {}

    def __init__(self, base, llm, config=None):
        self.base = base
        self.modules = {"llm": llm}
        self.config = dict(config if config is not None else {})


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


def test_bad_hunk_is_retried_instead_of_aborting(tmp_path):
    """hunk 原文匹配失败应变成一次可回修的轮次，而不是整任务崩溃。"""
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    llm = FakeLLM([_patch("not-in-file", "value = 2"), _patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -c "print(123)"' % sys.executable])
    r = agent.run("把 value 改成 2", approved_cb=lambda p: True)
    assert r["ok"] is True, r
    assert "value = 2" in (root / "m.py").read_text(encoding="utf-8")
    assert llm.calls == 2


def test_empty_patch_is_retried_as_no_progress(tmp_path):
    """new 与 old 相同 = 没有任何落盘改动，应回修而不是当成成功。"""
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    llm = FakeLLM([_patch("value = 1", "value = 1"), _patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -c "print(123)"' % sys.executable])
    r = agent.run("把 value 改成 2", approved_cb=lambda p: True)
    assert r["ok"] is True, r
    assert "value = 2" in (root / "m.py").read_text(encoding="utf-8")
    assert llm.calls == 2


def test_retry_prompt_contains_previous_diff(tmp_path, monkeypatch):
    """回修时把上一轮已应用的 diff 交给模型，避免重复同一份补丁。"""
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    llm = FakeLLM([_patch("value = 1", "value = 2"),
                   _patch("value = 2", "value = 3")])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(trunk, str(root))
    calls = {"n": 0}

    def fake_run_tests(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"ok": False, "results": [{
                "ok": False, "command": "pytest",
                "failures": [{"file": "tests/test_m.py", "test": "test_x"}],
                "output": "FAILED tests/test_m.py::test_x",
            }]}
        return {"ok": True, "results": []}

    monkeypatch.setattr(agent, "run_tests", fake_run_tests)
    monkeypatch.setattr(agent, "run_lint", lambda *a, **k: {"ok": True,
                                                           "results": []})
    r = agent.run("改成 3", approved_cb=lambda p: True)
    assert r["ok"] is True, r
    assert llm.calls == 2
    second = "\n".join(m["content"] for m in llm.messages[1])
    assert "上一轮已应用的改动" in second
    assert "value = 2" in second
    # 失败摘要里应保留失败用例名，方便模型定位。
    assert "tests/test_m.py::test_x" in second


def test_cancel_after_patch_generation_does_not_write_file(tmp_path):
    """生成 patch 期间用户取消：不能再落盘（否则"停了还在改文件"）。"""
    reset_run_registry()
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    llm = FakeLLM([_patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(trunk, str(root))
    original_chat = llm.chat
    approvals = []

    def chat_then_cancel(messages):
        out = original_chat(messages)
        agent.cancel()
        return out

    llm.chat = chat_then_cancel
    r = agent.run("把 value 改成 2",
                  approved_cb=lambda p: approvals.append(p) or True)

    assert r["cancelled"] is True, r
    assert approvals == [], "取消后不应再进入审批"
    assert "value = 1" in (root / "m.py").read_text(encoding="utf-8"), \
        "取消后文件仍被修改了"


def test_parse_test_failures_extracts_file_and_test():
    from core.code_agent import CodeAgent
    out = ('FAILED tests/test_a.py::test_x - AssertionError: boom\n'
           '  File "E:/p/m.py", line 12, in run\n'
           'AssertionError: bad')
    hits = CodeAgent.parse_test_failures(out)
    assert any(h["file"] == "tests/test_a.py" and h["test"] == "test_x"
               for h in hits)
    assert any(h["file"] == "E:/p/m.py" and h["line"] == 12 for h in hits)
