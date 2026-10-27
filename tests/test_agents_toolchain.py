# -*- coding: utf-8 -*-
"""三个子智能体的工具链单元测试（agent_analyst / agent_coder / agent_planner）。

为什么单独一个文件：
`test_lowcov_modules_extra.py` 只覆盖了“能跑通”的主路径，真正容易坏的是
分支边界——证据源失败、无模型降级、沙箱报错、计划 JSON 变形、同名工作流
覆盖策略。这些都不需要真实 LLM / 网络 / 沙箱，用假模块就能确定性地验证。

测试口径：
* 不联网、不调用真实模型、不启动子进程；
* 断言以“代码当前行为”为准，行为变了需要同步本文件和 docs/31。
"""
import json
import os
import sys
import types

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from modules.installed import agent_planner as planner_mod  # noqa: E402
from modules.installed.agent_analyst import AgentAnalyst  # noqa: E402
from modules.installed.agent_coder import AgentCoder  # noqa: E402
from modules.installed.agent_planner import AgentPlanner  # noqa: E402


# ---------------------------------------------------------------- 测试替身
class FakeTrunk:
    """最小 trunk：模块表 + call + base。

    `factories` 用来模拟 `_module()` 的按需加载：模块不在 modules 里时，
    trunk.call(name, "__no__") 会“加载”出一个实例。
    """

    def __init__(self, base):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        self.calls = []
        self.factories = {}

    def _log(self, _msg):
        pass

    def rule(self, _name, default=True):
        return default

    def call(self, module, method, *args, **kwargs):
        self.calls.append((module, method, args, kwargs))
        factory = self.factories.get(module)
        if factory is not None and module not in self.modules:
            self.modules[module] = factory()
        return {"ok": True}


class FakeLLM:
    """按脚本返回回复；可指定从第 N 次调用起抛异常。"""

    def __init__(self, replies=(), raises=None, fail_after=None):
        self.replies = list(replies)
        self.raises = raises
        self.fail_after = fail_after
        self.calls = 0
        self.prompts = []

    def chat(self, messages):
        self.calls += 1
        self.prompts.append(messages)
        if self.raises and (self.fail_after is None
                            or self.calls > self.fail_after):
            raise self.raises
        if not self.replies:
            return ""
        if len(self.replies) > 1:
            return self.replies.pop(0)
        return self.replies[0]


class FakeSearch:
    def __init__(self, payload=None, raises=None):
        self.payload = payload if payload is not None else {"结果": []}
        self.raises = raises
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        if self.raises:
            raise self.raises
        return self.payload


class FakeGraph:
    def __init__(self, triples=None, raises=None):
        self.triples = triples or []
        self.raises = raises
        self.queries = []

    def query(self, topic):
        self.queries.append(topic)
        if self.raises:
            raise self.raises
        return {"triples": self.triples}


class FakeRunner:
    """沙箱替身：记录传入代码与当次 timeout，按队列返回结果。"""

    def __init__(self, results=None, raises=None):
        self.timeout = 10
        self.results = list(results or [])
        self.raises = raises
        self.seen = []

    def run_code(self, code):
        self.seen.append({"code": code, "timeout": self.timeout})
        if self.raises:
            raise self.raises
        if not self.results:
            return {"成功": True, "stdout": "ok", "stderr": ""}
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


def _fail(stderr="traceback: boom"):
    return {"成功": False, "错误": stderr, "stderr": stderr}


class FakeWorkflowRunner:
    def __init__(self, ok=True):
        self.ok = ok
        self.started = []

    def start_async(self, name, payload=None):
        self.started.append((name, payload))
        return {"ok": self.ok}


def _plan_json():
    return json.dumps([
        {"id": "s1", "title": "确认目标", "action": "set",
         "args": {"value": "目标"}, "depends_on": [], "done_when": "清楚"},
        {"id": "s2", "title": "收集资料", "action": "search",
         "args": {"query": "资料"}, "depends_on": ["s1"],
         "done_when": "有资料"},
        {"id": "s3", "title": "形成方案", "action": "llm",
         "args": {"prompt": "写方案"}, "depends_on": ["s2"],
         "done_when": "有方案"},
        {"id": "s4", "title": "跑校验", "action": "code",
         "args": {"code": "print(1)"}, "depends_on": ["s1", "s3"],
         "done_when": "跑通"},
        {"id": "s5", "title": "等待确认", "action": "wait",
         "args": {"seconds": "2.5"}, "depends_on": ["s4"],
         "done_when": "确认"},
    ], ensure_ascii=False)


# ---------------------------------------------------------------- 元数据
def test_tools_metadata_matches_methods():
    """TOOLS 声明的 method 必须真实存在，参数/安全分级和文档一致。"""
    cases = [(AgentAnalyst, ("analyze", "compare")),
             (AgentCoder, ("solve", "run_code", "review")),
             (AgentPlanner, ("plan", "plan_to_workflow", "next_steps"))]
    for cls, methods in cases:
        names = [tool["name"] for tool in cls.TOOLS]
        assert len(names) == len(set(names)) == len(methods)
        assert tuple(tool["method"] for tool in cls.TOOLS) == methods
        for tool in cls.TOOLS:
            assert callable(getattr(cls, tool["method"], None))
            assert tool["hints"] and tool["desc"]
            assert tool["contract"]["params"]
    assert [t["name"] for t in AgentCoder.TOOLS if t.get("danger")] == [
        "agent_code_solve", "agent_code_run"]
    review = [t for t in AgentCoder.TOOLS if t["name"] == "agent_code_review"][0]
    assert review["readonly"] is True


# ---------------------------------------------------------------- 分析专家
def test_analyst_numbers_rows_and_rates():
    agent = AgentAnalyst(FakeTrunk("."))
    assert agent._numbers("延迟 -1.5 秒，提升 12%") == [-1.5, 12.0]
    rows = agent._numeric_rows("转化 0%，延迟 2.0", "转化 5%，延迟 1.5")
    assert rows[0] == {"序号": 1, "左": 0.0, "右": 5.0,
                       "差值": 5.0, "变化率": ""}
    assert rows[1]["差值"] == -0.5
    assert rows[1]["变化率"].startswith("-")
    assert len(agent._numeric_rows("只有 1 个", "有 2 个 3 个")) == 1


def test_analyst_evidence_from_search_and_graph():
    trunk = FakeTrunk(".")
    trunk.modules.update({
        "deep_search": FakeSearch({"结果": [
            {"title": "外部标题", "snippet": "外部摘要"},
            "纯文本结果",
            {"标题": "中文标题", "内容": "中文内容"},
            {"标题": "只有标题"},
        ]}),
        "graph_rag": FakeGraph([{"s": "A", "p": "导致", "o": "B"}]),
    })
    agent = AgentAnalyst(trunk)
    evidence, warnings = agent._evidence("测试")
    assert "外部标题：外部摘要" in evidence
    assert "纯文本结果" in evidence
    assert "中文标题：中文内容" in evidence
    assert "A --导致--> B" in evidence
    assert warnings == []


def test_analyst_evidence_failure_is_warning_not_error():
    trunk = FakeTrunk(".")
    trunk.modules.update({
        "deep_search": FakeSearch(raises=RuntimeError("搜索炸了")),
        "graph_rag": FakeGraph(raises=RuntimeError("图谱炸了")),
    })
    agent = AgentAnalyst(trunk)
    evidence, warnings = agent._evidence("测试")
    assert evidence == ""
    assert any("外部搜索失败" in w and "搜索炸了" in w for w in warnings)
    assert any("本地图谱查询失败" in w for w in warnings)


def test_analyst_evidence_follows_autoload_path():
    trunk = FakeTrunk(".")
    trunk.factories["deep_search"] = lambda: FakeSearch(
        {"结果": [{"title": "加载后", "snippet": "可用"}]})
    agent = AgentAnalyst(trunk)
    evidence, _ = agent._evidence("测试")
    assert "加载后：可用" in evidence
    assert ("deep_search", "__no__") in [(c[0], c[1]) for c in trunk.calls]


def test_analyst_evidence_truncated_to_3000():
    trunk = FakeTrunk(".")
    trunk.modules["graph_rag"] = FakeGraph([
        {"s": "S" * 300, "p": "P" * 300, "o": "O" * 300} for _ in range(8)])
    agent = AgentAnalyst(trunk)
    evidence, _ = agent._evidence("测试")
    assert len(evidence) == 3000


def test_analyst_analyze_without_llm_and_evidence():
    agent = AgentAnalyst(FakeTrunk("."))
    result = agent.analyze("要不要上线")
    assert result["ok"] is True
    assert result["llm"] is False
    assert "未识别到可配对的数值" in result["分析"]
    assert any("缺少外部证据" in risk for risk in result["风险"])
    assert result["数据对比"] == []


def test_analyst_compare_fallbacks_are_deterministic():
    agent = AgentAnalyst(FakeTrunk("."))
    b_better = agent.compare("成本 100 延迟 2", "成本 120 延迟 5")
    assert "B 更优" in b_better["分析"] and "2 项领先" in b_better["分析"]
    a_better = agent.compare("成本 100 延迟 2", "成本 80 延迟 1")
    assert "A 更优" in a_better["分析"]
    unknown = agent.compare("没有数字 A", "没有数字 B")
    assert "数据不足" in unknown["分析"]
    assert unknown["维度"] == "目标契合、成本、风险、可维护性"
    assert agent.compare("A", "")["error"]["code"] == "PLUGIN_MISSING_ARG"


def test_analyst_llm_exception_degrades_to_fallback():
    trunk = FakeTrunk(".")
    trunk.modules["llm"] = FakeLLM(raises=RuntimeError("模型挂了"))
    agent = AgentAnalyst(trunk)
    result = agent.compare("成本 10", "成本 20")
    assert result["ok"] is True and result["llm"] is False
    assert "LLM 调用失败" in agent._last_error
    assert "B 更优" in result["分析"]


def test_analyst_risks_include_baseline_caveat():
    agent = AgentAnalyst(FakeTrunk("."))
    claims = agent._risks("有证据", "有基准")
    assert any("口径一致" in risk for risk in claims)
    assert len(claims) == 2
    no_evidence = agent._risks("", "")
    assert any("缺少外部证据" in risk for risk in no_evidence)
    assert len(no_evidence) == 2


# ---------------------------------------------------------------- 编程小匠
def test_coder_extract_code_variants():
    assert AgentCoder._extract_code("```python\nprint(1)\n```") == "print(1)"
    assert AgentCoder._extract_code("```py\nx = 1\n```") == "x = 1"
    assert AgentCoder._extract_code(
        "说明\n```python\nfirst\n```\n```python\nsecond\n```") == "first"
    assert AgentCoder._extract_code("print('裸文本')") == "print('裸文本')"
    assert AgentCoder._extract_code("") == ""


def test_coder_solve_retries_with_stderr_and_appends_tests():
    trunk = FakeTrunk(".")
    runner = FakeRunner([_fail("NameError: x"), {"成功": True}])
    trunk.modules.update({
        "llm": FakeLLM(["```python\nprint(x)\n```", "```python\nprint(1)\n```"]),
        "code_runner": runner,
    })
    agent = AgentCoder(trunk)
    result = agent.solve("打印 1", tests="assert True")
    assert result["ok"] is True and result["运行成功"] is True
    assert result["轮次"] == 2
    assert [row["成功"] for row in result["修复记录"]] == [False, True]
    assert "NameError: x" in result["修复记录"][0]["错误"]
    assert "assert True" in runner.seen[0]["code"]
    assert "NameError: x" in str(trunk.modules["llm"].prompts[1])


def test_coder_solve_stops_after_two_fixes():
    trunk = FakeTrunk(".")
    trunk.modules.update({
        "llm": FakeLLM(["```python\nraise SystemExit(1)\n```"]),
        "code_runner": FakeRunner([_fail()]),
    })
    result = AgentCoder(trunk).solve("必定失败")
    assert result["ok"] is True and result["运行成功"] is False
    assert result["轮次"] == 3
    assert len(result["修复记录"]) == 3


def test_coder_solve_fix_round_llm_failure_keeps_last_code():
    trunk = FakeTrunk(".")
    trunk.modules.update({
        "llm": FakeLLM(["```python\nprint(1)\n```"],
                       raises=RuntimeError("模型断线"), fail_after=1),
        "code_runner": FakeRunner([_fail()]),
    })
    result = AgentCoder(trunk).solve("打印 1")
    assert result["ok"] is True and result["运行成功"] is False
    assert result["轮次"] == 1
    assert result["代码"] == "print(1)"


def test_coder_solve_non_python_only_generates():
    trunk = FakeTrunk(".")
    trunk.modules["llm"] = FakeLLM(["```js\nconsole.log(1)\n```"])
    result = AgentCoder(trunk).solve("打印 1", language="javascript")
    assert result["ok"] is True
    assert result["运行成功"] is None
    assert "不在沙箱执行" in result["说明"]
    assert result["语言"] == "javascript"
    assert result["修复记录"] == []
    trunk.modules.pop("llm")
    offline = AgentCoder(trunk).solve("打印 1", language="javascript")
    assert offline["error"]["code"] == "PLUGIN_NOT_AVAILABLE"


def test_coder_solve_requires_task_llm_and_runner():
    agent = AgentCoder(FakeTrunk("."))
    assert agent.solve("")["error"]["code"] == "PLUGIN_MISSING_ARG"
    assert agent.solve("任意")["error"]["code"] == "PLUGIN_NOT_AVAILABLE"
    trunk = FakeTrunk(".")
    trunk.modules["llm"] = FakeLLM(["```python\nprint(1)\n```"])
    agent = AgentCoder(trunk)
    # 有 LLM 但没有 code_runner → 明确报不可用，而不是把代码当本地进程跑
    assert agent.solve("任意")["error"]["code"] == "PLUGIN_NOT_AVAILABLE"
    trunk.modules["llm"] = FakeLLM([""])
    assert agent.solve("任意")["error"]["code"] == "PLUGIN_NOT_AVAILABLE"


def test_coder_run_code_timeout_override_restores():
    trunk = FakeTrunk(".")
    runner = FakeRunner()
    trunk.modules["code_runner"] = runner
    agent = AgentCoder(trunk)
    result = agent.run_code("print(1)", timeout=3)
    assert result["ok"] is True and result["运行成功"] is True
    assert runner.seen[0]["timeout"] == 3
    assert runner.timeout == 10
    assert agent.run_code("   ")["error"]["code"] == "PLUGIN_MISSING_ARG"
    trunk.modules.pop("code_runner")
    assert agent.run_code("print(1)")["error"]["code"] == "PLUGIN_NOT_AVAILABLE"


def test_coder_run_code_sandbox_exception_is_reported():
    trunk = FakeTrunk(".")
    trunk.modules["code_runner"] = FakeRunner(raises=OSError("沙箱进程起不来"))
    agent = AgentCoder(trunk)
    result = agent.run_code("print(1)")
    assert result["ok"] is True and result["运行成功"] is False
    assert "沙箱执行失败" in result["运行"]["错误"]
    assert "沙箱执行失败" in agent._last_error


def test_coder_review_never_executes():
    trunk = FakeTrunk(".")
    runner = FakeRunner()
    trunk.modules["code_runner"] = runner
    agent = AgentCoder(trunk)
    offline = agent.review("print('会执行吗')\n")
    assert offline["ok"] is True and offline["llm"] is False
    assert offline["问题"] == []
    assert "通过" in offline["审查"] and "LLM 不可用" in offline["审查"]
    assert runner.seen == []
    broken = agent.review("def f(:")
    assert any("语法错误" in issue for issue in broken["问题"])
    assert "有问题" in broken["审查"]
    assert agent.review("")["error"]["code"] == "PLUGIN_MISSING_ARG"


# ---------------------------------------------------------------- 策划专家
def test_planner_normalize_plan_sanitizes_input():
    agent = AgentPlanner(FakeTrunk("."))
    assert agent._normalize_plan("不是列表", "目标") is None
    assert agent._normalize_plan([], "目标") is None
    steps = agent._normalize_plan([
        "字符串项会被跳过",
        {"action": "不存在的动作", "title": "坏动作"},
        {"action": "code", "title": "没有代码"},
        {"action": "search", "title": "查一下"},
        {"action": "wait", "args": {"seconds": "不是数字"}},
        {"id": "a", "title": "第一步", "depends_on": []},
        {"id": "b", "title": "自依赖", "depends_on": ["b", "不存在"]},
        {"id": "c", "title": "字符串依赖", "depends_on": "a"},
    ], "目标")
    assert [step["id"] for step in steps] == [
        "s2", "s3", "s4", "s5", "a", "b", "c"]
    assert steps[0]["action"] == "llm"
    assert steps[0]["depends_on"] == []
    assert steps[1]["action"] == "llm"  # code 缺代码 → 降级 llm
    assert "编写并说明" in steps[1]["args"]["prompt"]
    assert steps[2]["args"]["query"] == "查一下"
    assert steps[3]["args"]["seconds"] == 0.0
    assert steps[5]["depends_on"] == []  # 自依赖和不存在的依赖都被剔除
    assert steps[6]["depends_on"] == ["a"]  # 字符串依赖会被规范化成列表
    dup = agent._normalize_plan(
        [{"id": "x", "title": "一"}, {"id": "x", "title": "二"}], "目标")
    assert [step["id"] for step in dup] == ["x", "s2"]


def test_planner_plan_parses_fenced_json():
    trunk = FakeTrunk(".")
    reply = "这是计划：\n```json\n%s\n```" % _plan_json()
    trunk.modules["llm"] = FakeLLM([reply])
    result = AgentPlanner(trunk).plan("目标", constraints="一周内")
    assert result["ok"] is True and result["llm"] is True
    assert [s["id"] for s in result["步骤"]] == ["s1", "s2", "s3", "s4", "s5"]
    assert "一周内" in str(trunk.modules["llm"].prompts[0])


def test_planner_plan_garbage_and_offline_fall_back():
    trunk = FakeTrunk(".")
    trunk.modules["llm"] = FakeLLM(["完全不是 JSON"])
    agent = AgentPlanner(trunk)
    garbage = agent.plan("目标")
    assert garbage["ok"] is True
    assert [s["action"] for s in garbage["步骤"]] == [
        "set", "search", "llm", "wait"]
    # 记录当前边界：有回复但解析失败时 llm=True、警告为空（见 docs/31 4.5）
    assert garbage["llm"] is True and garbage["警告"] == []
    assert "计划 JSON 解析失败" in agent._last_error

    offline = AgentPlanner(FakeTrunk(".")).plan("目标")
    assert offline["llm"] is False
    assert offline["警告"]
    assert offline["步骤"][0]["args"]["value"] == "目标"


def test_planner_workflow_name_sanitize_and_overwrite(tmp_path):
    trunk = FakeTrunk(tmp_path)
    trunk.modules["llm"] = FakeLLM([_plan_json()])
    agent = AgentPlanner(trunk)
    first = agent.plan_to_workflow("目标一", name="../坏 名字!")
    assert first["ok"] is True
    assert os.path.basename(first["文件"]) == "坏_名字.yaml"
    assert agent.plan_to_workflow("目标二", name="坏_名字")["ok"] is False
    replaced = agent.plan_to_workflow(
        "目标二", name="坏_名字", overwrite=True)
    assert replaced["ok"] is True
    assert agent.plan_to_workflow("目标三", name="x" * 60)["ok"] is True
    default = agent.plan_to_workflow("目标四")
    assert os.path.basename(default["文件"]).startswith("agent_plan_")


def test_planner_workflow_fields_and_single_dependency(tmp_path):
    trunk = FakeTrunk(tmp_path)
    trunk.modules["llm"] = FakeLLM([_plan_json()])
    agent = AgentPlanner(trunk)
    written = agent.plan_to_workflow("目标", name="fields")
    yaml = pytest.importorskip("yaml")
    with open(written["文件"], encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    steps = {step["name"]: step for step in payload["steps"]}
    assert steps["确认目标"]["value"] == "目标"
    assert steps["收集资料"]["query"] == "资料"
    assert steps["形成方案"]["prompt"] == "写方案"
    assert steps["跑校验"]["code"] == "print(1)"
    assert steps["等待确认"]["seconds"] == 2.5
    assert steps["收集资料"]["when"] == "确认目标"
    assert "when" not in steps["跑校验"]  # 多依赖不展开成扇入
    assert written["步骤"] == 5


def test_planner_workflow_run_hook_and_missing_runner(tmp_path):
    trunk = FakeTrunk(tmp_path)
    trunk.modules.update({
        "llm": FakeLLM([_plan_json()]),
        "workflow_runner": FakeWorkflowRunner(),
    })
    agent = AgentPlanner(trunk)
    started = agent.plan_to_workflow("目标", name="run_ok", run="true")
    assert started["已启动"] is True
    name, payload = trunk.modules["workflow_runner"].started[0]
    assert name == "run_ok" and payload == {"input": "目标"}
    trunk.modules["workflow_runner"] = FakeWorkflowRunner(ok=False)
    assert agent.plan_to_workflow(
        "目标", name="run_fail", run=True)["已启动"] is False
    trunk.modules.pop("workflow_runner")
    assert agent.plan_to_workflow(
        "目标", name="no_runner", run=True)["已启动"] is False


def test_planner_workflow_write_failure_returns_internal_error(
        tmp_path, monkeypatch):
    trunk = FakeTrunk(tmp_path)
    trunk.modules["llm"] = FakeLLM([_plan_json()])

    def _boom(*_args, **_kwargs):
        raise OSError("磁盘满了")

    # 只替换该模块看到的 os，避免真的改到全局 os.replace
    monkeypatch.setattr(planner_mod, "os", types.SimpleNamespace(
        makedirs=os.makedirs, path=os.path, replace=_boom))
    agent = AgentPlanner(trunk)
    result = agent.plan_to_workflow("目标", name="broken")
    assert result["ok"] is False
    assert result["error"]["code"] == "PLUGIN_INTERNAL_ERROR"
    assert "磁盘满了" in agent._last_error


def test_planner_next_steps_variants():
    trunk = FakeTrunk(".")
    agent = AgentPlanner(trunk)
    steps = json.loads(_plan_json())
    blocked = agent.next_steps(steps)
    assert blocked["可执行"] == ["s1"]
    assert blocked["阻塞"] == ["s2", "s3", "s4", "s5"]
    ready = agent.next_steps(steps, done=["s1", "s2"])
    assert ready["可执行"] == ["s3"]
    assert "s4" in ready["阻塞"]
    assert ready["已完成"] == ["s1", "s2"]
    unknown_done = agent.next_steps(steps, done="zzz")
    assert unknown_done["已完成"] == ["zzz"]
    assert unknown_done["可执行"] == ["s1"]
    ignored = agent.next_steps([
        {"id": "a", "depends_on": ["not-exist"]},
        "非字典项",
        {"id": "", "depends_on": []},
    ])
    assert ignored["可执行"] == ["a"] and ignored["剩余"] == ["a"]
    assert agent.next_steps(
        "不是 JSON", "")["error"]["code"] == "PLUGIN_BAD_INPUT"
    assert agent.next_steps(
        {"id": "a"}, "")["error"]["code"] == "PLUGIN_BAD_INPUT"


def test_planner_truthy_and_missing_goal(tmp_path):
    agent = AgentPlanner(FakeTrunk(tmp_path))
    for value in (True, "true", "TRUE", "yes", "1", "是"):
        assert agent._truthy(value) is True
    for value in (False, "false", "", None, "0", 0, "否"):
        assert agent._truthy(value) is False
    assert agent.plan("")["error"]["code"] == "PLUGIN_MISSING_ARG"
    assert agent.plan_to_workflow("   ")["error"]["code"] == "PLUGIN_MISSING_ARG"
