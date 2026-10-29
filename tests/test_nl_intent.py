# -*- coding: utf-8 -*-
"""工作台意图层（批次 44.1）：schema、三段式路由、追问、影子记录。

标注集 36 条，覆盖斜杠命令、文件/符号目标、撤销、测试、计划与闲聊；
要求意图准确率 ≥90%（当前规则档全对），并且破坏性意图绝不自动执行。
"""
import json

import pytest

from core.agent_router import route_goal
from core.nl import intent as nl


CASES = [
    ("/fix 这个报错", "fix_error"),
    ("/test tests/test_nl_intent.py", "run_test"),
    ("/explain core/agent_router.py", "explain"),
    ("/plan 把路由拆开", "plan"),
    ("/undo", "undo"),
    ("修复 core/agent_router.py 的 pytest 报错", "fix_error"),
    ("跑一下测试，看看有没有回归", "run_test"),
    ("跑 tests/test_nl_intent.py", "run_test"),
    ("解释一下 core/chat/state.py 里的分类逻辑", "explain"),
    ("这段代码干嘛的", "explain"),
    ("把 core/code_agent.py 里的 propose_patch 重构一下，拆成两个函数", "refactor"),
    ("重构整个项目的路由层", "refactor"),
    ("搜索 workspace_index 里的 find_symbols", "search"),
    ("find_symbols 在哪定义的", "search"),
    ("谁调用 propose_patch", "search"),
    ("打开 gui/ide_sidebar.py", "open_file"),
    ("跳到 test_nl_intent.py", "open_file"),
    ("撤销刚才的修改", "undo"),
    ("回滚上一次自动修改", "undo"),
    ("给我一个重构计划", "plan"),
    ("帮我实现一个函数，读取配置", "edit_code"),
    ("在 core/chat/state.py 里加一个字段 mood", "edit_code"),
    ("删掉 tests/test_memory_jobs.py 里重复的用例", "edit_code"),
    ("把 build 函数重命名成 compile_all", "edit_code"),
    ("运行 tests/test_nl_intent.py", "run_test"),
    ("pytest 跑一下", "run_test"),
    ("解释一下这个函数", "explain"),
    ("帮我看看为什么保存失败", "fix_error"),
    ("今天天气怎么样", "chat"),
    ("你好呀", "chat"),
    ("这段代码什么意思", "explain"),
    ("把 tests/test_x.py 跑起来", "run_test"),
    ("帮我补上缺失的测试", "edit_code"),
    ("整个项目格式化一下", "edit_code"),
    ("这个函数为什么报错", "fix_error"),
    ("搜索配置文件里的 timeout", "search"),
]


class _Ctx:
    def __init__(self):
        self.rows = []

    def record_shadow(self, payload):
        self.rows.append(payload)
        return True


class _Trunk:
    def __init__(self, mode="shadow", rules=None):
        self._mode = mode
        self._rules = dict(rules or {})
        self.ctx = _Ctx()

    def rule(self, name, default=None):
        if name == "nl.intent_v2":
            return self._mode
        return self._rules.get(name, default)


def test_labeled_accuracy_at_least_90_percent():
    hits = [text for text, want in CASES
            if nl.route(text)["intent"] == want]
    assert len(hits) / float(len(CASES)) >= 0.9, (
        "意图准确率不足：%d/%d" % (len(hits), len(CASES)))


@pytest.mark.parametrize("text,want", CASES, ids=[c[0][:18] for c in CASES])
def test_each_labeled_case(text, want):
    info = nl.route(text)
    assert info["intent"] == want, info
    assert 0.0 <= info["confidence"] <= 1.0
    assert info["stage"] in ("rule", "model", "clarify")


def test_schema_fields_are_stable():
    info = nl.route("修复 core/code_agent.py 里 propose_patch 的报错")
    assert set(("intent", "targets", "scope", "constraints", "risk",
                "confidence", "reason", "stage", "auto_execute")) <= set(info)
    kinds = [t["type"] for t in info["targets"]]
    assert "file" in kinds and "symbol" in kinds
    assert info["intent"] == "fix_error"
    assert info["risk"] == "medium"


def test_targets_file_and_symbol_values():
    info = nl.route("看看 gui/ide_sidebar.py 的 CommandCenterMixin")
    values = [t["value"] for t in info["targets"]]
    assert "gui/ide_sidebar.py" in values
    assert info["scope"] in ("file", "function", "selection", "project")


def test_scope_selection_and_project():
    assert nl.route("解释一下选中的这段代码")["scope"] == "selection"
    assert nl.route("格式化整个项目")["scope"] == "project"


def test_constraints_are_picked_up():
    info = nl.route("重构 core/code_agent.py，不要改公开接口")
    assert any("不要改公开接口" in c for c in info["constraints"])


def test_destructive_intents_never_auto_execute():
    undo = nl.route("撤销刚才的修改")
    assert undo["intent"] == "undo"
    assert undo["risk"] == "high"
    assert undo["auto_execute"] is False
    refactor = nl.route("重构整个项目的路由层")
    assert refactor["risk"] == "high"
    assert refactor["auto_execute"] is False


def test_safe_intent_can_auto_execute():
    info = nl.route("/test tests/test_nl_intent.py")
    assert info["intent"] == "run_test"
    assert info["risk"] == "low"
    assert info["auto_execute"] is True


def test_low_confidence_asks_one_question():
    info = nl.route("帮我改一下这个")
    assert info["intent"] == "edit_code"
    assert info["stage"] == "clarify"
    assert "哪个文件或符号" in info["clarify"]
    assert info["auto_execute"] is False


def test_run_test_without_target_asks_which_test():
    info = nl.route("帮我测试一下")
    assert info["clarify"]
    assert "哪个测试" in info["clarify"]


def test_slash_commands_cover_workbench_actions():
    mapping = {"/open": "open_file", "/test": "run_test",
               "/explain": "explain", "/fix": "fix_error",
               "/code": "edit_code", "/refactor": "refactor",
               "/search": "search", "/undo": "undo", "/plan": "plan"}
    for head, want in mapping.items():
        assert nl.route(head + " x")["intent"] == want


def test_model_stage_parses_json():
    def model_call(prompt):
        assert "只输出 JSON" in prompt
        return json.dumps({
            "intent": "edit_code",
            "targets": [{"type": "file", "value": "core/x.py"}],
            "scope": "function",
            "constraints": ["保持兼容"],
        })

    info = nl.route("帮我弄一下那个东西", model_call=model_call)
    assert info["intent"] == "edit_code"
    assert info["stage"] == "model"
    assert info["targets"] == [{"type": "file", "value": "core/x.py"}]
    assert info["scope"] == "function"
    assert info["constraints"] == ["保持兼容"]


def test_model_output_with_code_fence_is_parsed():
    info = nl.route(
        "随便弄弄", model_call=lambda _p: "```json\n"
        '{"intent": "search", "targets": []}\n```')
    assert info["intent"] == "search"


def test_bad_model_output_falls_back_to_rule():
    info = nl.route("今天天气怎么样", model_call=lambda _p: "我不知道")
    assert info["intent"] == "chat"


def test_model_not_called_when_rule_is_confident():
    called = []

    def model_call(_prompt):
        called.append(1)
        return '{"intent": "chat"}'

    info = nl.route("/undo", model_call=model_call)
    assert info["intent"] == "undo" and not called


def test_mode_defaults_to_shadow_and_rejects_unknown():
    assert nl.mode(_Trunk("shadow")) == "shadow"
    assert nl.mode(_Trunk("ON")) == "on"
    assert nl.mode(_Trunk("banana")) == "shadow"


def test_record_shadow_writes_one_row():
    trunk = _Trunk()
    info = nl.route("修复 core/x.py 的报错")
    assert nl.record_shadow(trunk, info, "修复 core/x.py 的报错") is True
    row = trunk.ctx.rows[-1]
    assert row["kind"] == "nl_intent"
    assert row["intent"] == "fix_error"
    assert "core/x.py" in row["targets"]


# ── 与统一路由的衔接（旧三词表仍是第一段） ──
def test_router_without_trunk_is_unchanged():
    info = route_goal("修复 tests/test_x.py 的 pytest 报错")
    assert info["kind"] == "code"
    assert "nl" not in info


def test_router_off_mode_is_unchanged():
    info = route_goal("找一下 foo_bar 在哪儿", trunk=_Trunk("off"))
    assert info["kind"] == "chat"
    assert "nl" not in info


def test_router_shadow_keeps_kind_but_records():
    trunk = _Trunk("shadow")
    info = route_goal("找一下 foo_bar 在哪儿", trunk=trunk)
    assert info["kind"] == "chat"
    assert info["nl"]["intent"] == "search"
    assert trunk.ctx.rows and trunk.ctx.rows[-1]["kind"] == "nl_intent"


def test_router_on_upgrades_chat_with_explicit_target():
    info = route_goal("找一下 foo_bar 在哪儿", trunk=_Trunk("on"))
    assert info["nl"]["intent"] == "search"
    assert info["kind"] == "code"


def test_router_on_never_steals_computer_domain():
    info = route_goal("打开浏览器搜索天气并截图", trunk=_Trunk("on"))
    assert info["kind"] == "computer"
    assert info["nl"]["intent"] in nl.INTENTS


def test_router_on_keeps_code_domain_and_enriches_reason():
    info = route_goal("修复 core/code_agent.py 的报错", trunk=_Trunk("on"))
    assert info["kind"] == "code"
    assert "意图:fix_error" in info["reason"]
