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


_COMPLEX_GOAL = "重构 m.py 的计算逻辑并补测试，保证原有行为不变"
_PLAN_JSON = json.dumps({
    "summary": "重构计算逻辑并补测试",
    "steps": [
        {"title": "确认现有行为", "purpose": "读 m.py 与相关测试",
         "files": ["m.py"], "risk": "low"},
        {"title": "应用最小修改", "purpose": "改 value 并跑测试",
         "files": ["m.py"], "risk": "medium"},
    ],
    "risks": ["改动可能影响调用方"],
    "tests": ["pytest -q"],
}, ensure_ascii=False)


def _plan_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "m.py").write_text("value = 1\n", encoding="utf-8")
    return root


def test_plan_rejected_does_not_modify_files(tmp_path):
    """拒绝计划：零落盘，也不进入 patch 审批。"""
    reset_run_registry()
    root = _plan_project(tmp_path)
    llm = FakeLLM([_PLAN_JSON, _patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(trunk, str(root))
    plans, approvals = [], []

    r = agent.run(_COMPLEX_GOAL,
                  approved_cb=lambda p: approvals.append(p) or True,
                  plan_cb=lambda p: plans.append(p) or False)

    assert r["cancelled"] is True, r
    assert r.get("rejected_plan") is True, r
    assert len(plans) == 1 and plans[0]["steps"], plans
    assert approvals == [], "拒绝计划后不应进入 patch 审批"
    assert llm.calls == 1, "拒绝计划后不应继续请求 patch"
    assert "value = 1" in (root / "m.py").read_text(encoding="utf-8")


def test_plan_approved_then_applies_patch(tmp_path):
    """确认计划后照常生成 patch、应用并跑测试。"""
    reset_run_registry()
    root = _plan_project(tmp_path)
    llm = FakeLLM([_PLAN_JSON, _patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -c "print(123)"' % sys.executable])
    plans = []
    r = agent.run(_COMPLEX_GOAL,
                  approved_cb=lambda p: True,
                  plan_cb=lambda p: plans.append(p) or True)

    assert r["ok"] is True, r
    assert len(plans) == 1
    assert any(s.get("title") for s in plans[0]["steps"])
    assert "value = 2" in (root / "m.py").read_text(encoding="utf-8")
    assert llm.calls == 2


class FakeStreamLLM:
    """只有 stream_chat 的模型：验证取消令牌确实传到了生成调用。"""

    def __init__(self):
        self.token_seen = False
        self.agent = None

    def chat(self, messages):
        raise AssertionError("应优先走可取消的 stream_chat")

    def stream_chat(self, messages, cancel_token=None):
        self.token_seen = cancel_token is not None
        if self.agent is not None:
            self.agent.cancel()
        return ""


def test_cancel_during_stream_generation(tmp_path):
    """单次模型生成期间取消：立即结束，不进入审批、不落盘。"""
    reset_run_registry()
    root = _plan_project(tmp_path)
    llm = FakeStreamLLM()
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(trunk, str(root))
    llm.agent = agent
    approvals = []

    r = agent.run("把 value 改成 2",
                  approved_cb=lambda p: approvals.append(p) or True)

    assert llm.token_seen is True
    assert r["cancelled"] is True, r
    assert approvals == []
    assert "value = 1" in (root / "m.py").read_text(encoding="utf-8")


def test_simple_goal_skips_plan(tmp_path):
    """简单目标不打扰用户：不生成计划，直接执行。"""
    reset_run_registry()
    root = _plan_project(tmp_path)
    llm = FakeLLM([_patch()])
    trunk = FakeTrunk(str(root), llm, {"code_agent": {"two_role": False}})
    agent = CodeAgent(
        trunk, str(root),
        test_commands=['"%s" -c "print(123)"' % sys.executable])
    plans = []
    r = agent.run("把 value 改成 2",
                  approved_cb=lambda p: True,
                  plan_cb=lambda p: plans.append(p) or True)

    assert r["ok"] is True, r
    assert plans == [], "简单目标不应触发计划审批"
    assert llm.calls == 1


def test_plan_helpers_cover_gates_and_fallback_text(monkeypatch):
    """计划开关、复杂度启发式、文本渲染与非法输出降级。"""
    from core import code_plan as cp

    monkeypatch.setenv("X6_CODE_AGENT_PLAN", "off")
    assert cp.plan_enabled(FakeTrunk(".", object())) is False
    monkeypatch.delenv("X6_CODE_AGENT_PLAN")
    assert cp.plan_enabled(
        FakeTrunk(".", object(), {"code_agent": {"plan_approval": False}})) is False
    assert cp.plan_enabled(
        FakeTrunk(".", object(), {"code_agent": "坏配置"})) is True

    class _OddConfig:
        config = "不是字典"

    assert cp.plan_enabled(_OddConfig()) is True

    assert cp.needs_plan("x" * 40) is True
    assert cp.needs_plan("加个参数") is False
    assert cp.needs_plan("加个参数", ["a", "b", "c", "d", "e"]) is True

    empty = cp.heuristic_plan("", ["a.py"])
    assert empty["summary"] and empty["fallback"] is True

    text = cp.plan_text({
        "summary": "", "steps": [
            {"title": "改文件", "purpose": "保持行为", "files": ["x.py"],
             "risk": "critical"},
            {"title": "跑测试"},
        ],
        "risks": ["可能与调用方冲突"], "tests": ["pytest -q"],
    })
    assert "执行步骤" in text and "x.py" in text
    assert "critical" in text and "验证命令" in text
    assert cp.plan_text(None)


def test_normalize_plan_recovers_from_bad_model_output():
    from core import code_plan as cp

    assert cp.normalize_plan("不是字典", "目标")["fallback"] is True
    plan = cp.normalize_plan({"plan": {
        "summary": "嵌套计划",
        "steps": ["第一步", {"purpose": "缺标题"}, {
            "title": "改文件", "files": "不是列表", "risk": "HIGH"}],
        "risks": "不是列表",
        "tests": ["pytest", "pytest", ""],
    }}, "目标")
    assert [s["title"] for s in plan["steps"]] == ["第一步", "改文件"]
    assert plan["steps"][1]["risk"] == "high"
    assert plan["risks"] == []
    assert plan["tests"] == ["pytest"]
    assert cp.normalize_plan({"steps": []}, "目标")["fallback"] is True


def test_build_plan_degrades_without_llm_or_on_error(tmp_path):
    from core import code_plan as cp

    class _NoLlm:
        trunk = type("T", (), {"modules": {}})()

    assert cp.build_plan(_NoLlm(), "目标", {"files": []})["fallback"] is True

    class _BadLLM:
        def chat(self, messages):
            raise RuntimeError("模型炸了")

    reset_run_registry()
    root = _plan_project(tmp_path)
    agent = CodeAgent(FakeTrunk(str(root), _BadLLM()), str(root))
    plan = cp.build_plan(agent, "目标", {"files": ["m.py"]})
    assert plan["fallback"] is True


def test_orchestrator_forwards_plan_approval():
    from core.agent_orchestrator import AgentOrchestrator

    seen = []
    trunk = FakeTrunk(".", object())
    orch = AgentOrchestrator(
        trunk, root=".",
        approval_cb=lambda kind, payload: seen.append((kind, payload)) or True)
    assert orch._approve_plan({"steps": []}) is True
    assert seen == [("plan", {"steps": []})]
    assert AgentOrchestrator(trunk, root=".")._approve_plan({}) is True
