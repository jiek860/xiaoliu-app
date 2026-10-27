# -*- coding: utf-8 -*-
"""低覆盖模块补测：记忆闭环、学习闭环、调度器、深度搜索、多模态。"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from modules.installed.memory_loop import MemoryPipeline  # noqa: E402
from modules.installed.learning_loop import LearningPipeline  # noqa: E402
from modules.installed.scheduler import Scheduler  # noqa: E402
from modules.installed.deep_search import DeepSearch  # noqa: E402
from modules.installed.multimodal import Multimodal  # noqa: E402
from modules.installed.graph_rag import GraphRAG  # noqa: E402
from modules.installed.workflow_runner import WorkflowRunner  # noqa: E402
from modules.installed.agent_analyst import AgentAnalyst  # noqa: E402
from modules.installed.agent_coder import AgentCoder  # noqa: E402
from modules.installed.agent_planner import AgentPlanner  # noqa: E402


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        self.logs = []
        self.calls = []

    def _log(self, msg):
        self.logs.append(msg)

    def rule(self, _name, default=True):
        return default

    def call(self, module, method, *args, **kwargs):
        self.calls.append((module, method, args, kwargs))
        if module == "memory_cards":
            return {"已总结": True}
        if module == "forgetting_curve" and method == "due_review":
            return {"项目": ["key1"]}
        if module == "vector_store" and method == "search":
            return [{"text": "相关记忆"}]
        if module == "vector_store" and method == "add":
            return {"ok": True}
        if module == "deep_search" and method == "search":
            return {"结果": [{"标题": "T", "链接": "http://x", "摘要": "S"}]}
        return {"ok": True}

    def kb_add(self, *_a, **_k):
        return {"ok": True}


def test_memory_loop_full_cycle(tmp_path):
    m = MemoryPipeline(_Trunk(tmp_path))
    assert m._scene("python 报错") == "编程"
    assert m._scene("今天天气") == "闲聊"
    assert m._scene("普通") == "日常"
    scene = m.remember_scene("python 代码", "好的")
    assert scene == "编程"
    assert m.episodic(scene="编程")
    assert m.recall("Python")
    r = m.run("我喜欢 Python", "好的")
    assert r["ok"] and r["本次复习"] == 1 and r["检索增强"] == 1
    assert m.compress_old_memories(0)["压缩数"] >= 1
    assert m.recall_from_month_ago("Python")["找到"] >= 1
    assert "串联" in m.link_memories("Python")
    assert m.forget_old_memories(0)["遗忘后"] >= 0
    assert m._age_days("bad") == 0.0


def test_learning_loop_cycle_and_control(tmp_path, monkeypatch):
    t = _Trunk(tmp_path)
    lp = LearningPipeline(t)
    d, topic = lp.collect_gap()
    assert d and topic
    assert lp.fetch("Python")[0]["标题"] == "T"
    n = lp.store(d, topic, lp.fetch("Python"))
    assert n == 1
    rep = lp.report(d, topic, n)
    assert rep["入库条数"] == 1
    assert lp.run("Python 测试")["ok"] is True
    assert lp.status()["连续学习运行中"] is False
    monkeypatch.setattr(
        "threading.Thread",
        lambda *a, **k: type("T", (), {"start": lambda self: None})())
    assert "启动" in lp.start_continuous(interval=0)
    lp.stop_continuous()
    assert isinstance(lp.recommend(), str)
    assert lp.feedback("Python", True)["已记录"] == "正面反馈"


def test_scheduler_basics(tmp_path):
    t = _Trunk(tmp_path)
    s = Scheduler(t)
    assert "运行中" in s.status()
    ran = []
    s._safe_run("test", lambda: ran.append(1))
    assert ran == [1]
    assert isinstance(s.run(), dict)
    s.start()
    assert s.running is True
    s.stop()
    assert s.running is False
    assert s._safe_run("失败", lambda: (_ for _ in ()).throw(RuntimeError("x"))) is False


def test_deep_search_parsers_and_search(tmp_path, monkeypatch):
    t = _Trunk(tmp_path)
    ds = DeepSearch(t)
    assert ds._clean("<b>a</b>&amp;") == "a&amp;"
    assert ds._is_code_query("Python 报错 stacktrace")
    html = '<li class="b_algo"><h2><a href="http://a">标题</a></h2><p>摘要</p></li>'
    monkeypatch.setattr(ds, "_get", lambda *a, **k: html)
    assert isinstance(ds._bing("q"), list)
    assert isinstance(ds._sogou("q"), list)
    assert isinstance(ds._ddg("q"), list)
    assert ds._github("q") is None or isinstance(ds._github("q"), list)
    r = ds.search("Python 报错")
    assert isinstance(r, dict)
    assert ds.run("test") is not None


def test_multimodal_missing_files_and_stats(tmp_path):
    t = _Trunk(tmp_path)
    mm = Multimodal(t)
    assert mm.describe_image(str(tmp_path / "missing.png"))["错误"] == "图片不存在"
    assert mm.transcribe_audio(str(tmp_path / "missing.wav"))["错误"] == "音频文件不存在"
    assert mm.describe_video(str(tmp_path / "missing.mp4"))["错误"]
    assert mm.capture_camera(str(tmp_path / "x.jpg"))["错误"]
    assert mm.find_object("cat")["错误"]
    mm.history.append({"x": 1})
    assert isinstance(mm.get_history(), list)
    mm.clear_history()
    assert mm.stats()["历史记录数"] == 0
    assert "图片描述次数" in mm.run()

def test_forgetting_curve_migrates_legacy_list(tmp_path):
    """旧版 forgetting.json 是 list，不能让 remember/due_review 崩。"""
    import json
    from modules.installed.forgetting_curve import ForgettingCurve

    p = tmp_path / "data" / "forgetting.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([
        {"text": "旧记忆", "time": 1, "imp": 0.5, "review": 2},
        {"text": "旧记忆", "time": 2, "imp": 0.5, "review": 1},
    ], ensure_ascii=False), encoding="utf-8")
    fc = ForgettingCurve(_Trunk(tmp_path))
    assert isinstance(fc.memory, dict)
    assert len(fc.memory) == 2
    assert fc.remember("新记忆", "内容")["记住"] == "新记忆"
    assert fc.due_review()["待复习"] >= 1
    assert isinstance(json.loads(p.read_text(encoding="utf-8")), dict)


def test_graph_rag_build_query_lifecycle(tmp_path):
    t = _Trunk(tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "graph.json").write_text(json.dumps({
        "三元组": [
            {"s": "Python", "p": "用于", "o": "数据分析"},
            {"s": "Python", "p": "属于", "o": "编程语言"},
            {"s": "数据库", "p": "用于", "o": "存储"},
            {"s": "数据结构", "p": "属于", "o": "计算机科学"},
            {"s": "数据库", "p": "属于", "o": "计算机科学"},
        ]
    }, ensure_ascii=False), encoding="utf-8")
    g = GraphRAG(t)
    assert g.start()["ok"] is True
    assert g.health()["stage"] == "started"
    built = g.build()
    assert built["ok"] is True and built["communities"] >= 1
    assert os.path.exists(g.out_file)
    q = g.query("Python 数据分析")
    assert q["ok"] is True
    assert q["relevant_communities"]
    assert any(row["s"] == "Python" for row in q["triples"])
    assert g.status()["社区"] >= 1
    assert g.run("Python")["ok"] is True
    g.stop()
    assert g.health()["stage"] == "stopped"


def test_graph_rag_empty_or_broken_graph(tmp_path):
    t = _Trunk(tmp_path)
    g = GraphRAG(t)
    r = g.build()
    assert r["ok"] is False and r["error"]["code"] == "PLUGIN_NOT_AVAILABLE"
    assert g.query("")["error"]["code"] == "PLUGIN_MISSING_ARG"
    p = tmp_path / "data" / "graph.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{坏 json", encoding="utf-8")
    r = GraphRAG(t).build()
    assert r["ok"] is False and r["error"]["code"] == "PLUGIN_NOT_AVAILABLE"


def _write_workflow(root, name, text):
    folder = root / "data" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (name + ".yaml")).write_text(text, encoding="utf-8")


def test_workflow_runner_conditions_and_failure_policy(tmp_path):
    _write_workflow(tmp_path, "branch", """
name: 分支测试
steps:
  - name: 第一步
    action: set
    value: ok
  - name: 会跑
    action: set
    value: "{{第一步}}!"
    when: "第一步 == ok"
  - name: 不跑
    action: set
    value: no
    when: "第一步 != ok"
""")
    _write_workflow(tmp_path, "tolerant", """
name: 容错测试
steps:
  - name: 坏步骤
    action: nope
    on_error: continue
  - name: 好步骤
    action: set
    value: done
""")
    _write_workflow(tmp_path, "broken", """
name: 失败测试
steps:
  - name: 坏步骤
    action: nope
""")
    t = _Trunk(tmp_path)
    w = WorkflowRunner(t)
    r = w.run("branch")
    assert r["ok"] is True
    assert r["results"][1]["result"] == "ok!"
    assert r["results"][2]["skipped"] is True
    tolerant = w.run("tolerant")
    assert tolerant["ok"] is True
    assert tolerant["results"][0]["ok"] is False
    assert tolerant["results"][1]["result"] == "done"
    broken = w.run("broken")
    assert broken["ok"] is False and broken["failed_step"] == "坏步骤"
    assert broken["error"]["code"] == "PLUGIN_INTERNAL_ERROR"


def test_workflow_runner_llm_search_code_actions(tmp_path):
    _write_workflow(tmp_path, "actions", """
name: 动作测试
steps:
  - name: 搜索
    action: search
    query: "{{input}}"
  - name: 总结
    action: llm
    prompt: "总结：{{prev}}"
  - name: 运行
    action: code
    code: "print('hi')"
""")

    class _Search:
        def search(self, query):
            return {"ok": True, "结果": [{"标题": query}]}

    class _LLM:
        def chat(self, prompt):
            return "摘要:" + str(prompt)[-20:]

    class _Runner:
        def run_code(self, code, timeout=30):
            return {"成功": True, "stdout": "hi"}

    t = _Trunk(tmp_path)
    t.modules.update({"deep_search": _Search(), "llm": _LLM(),
                      "code_runner": _Runner()})
    w = WorkflowRunner(t)
    r = w.run("actions", input="Python")
    assert r["ok"] is True
    assert r["results"][0]["result"]["结果"][0]["标题"] == "Python"
    assert "摘要:" in r["results"][1]["result"]
    assert r["results"][2]["result"]["stdout"] == "hi"

    class _BadRunner:
        def run_code(self, code, timeout=30):
            return {"成功": False, "stderr": "SyntaxError"}

    t.modules["code_runner"] = _BadRunner()
    bad = w.run("actions", input="Python")
    assert bad["ok"] is False and bad["failed_step"] == "运行"


def test_workflow_runner_templates_retry_and_tick(tmp_path, monkeypatch):
    _write_workflow(tmp_path, "retry", """
name: 重试测试
steps:
  - name: 重试步骤
    action: set
    value: ok
    retry: 1
""")
    _write_workflow(tmp_path, "scheduled", """
name: 定时测试
schedule: "* * * * *"
steps:
  - name: 定时步骤
    action: set
    value: tick
""")
    w = WorkflowRunner(_Trunk(tmp_path))
    assert "daily_digest" in w.list_workflows()
    assert w.templates()
    first = w.ensure_templates()
    assert first["ok"] is True and "daily_digest" in first["written"]
    assert os.path.exists(os.path.join(w.workflow_dir, "daily_digest.yaml"))
    assert w.ensure_templates()["existing"]
    assert w.load("daily_digest")["steps"]
    calls = {"n": 0}

    def flaky(action, step, context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("第一次失败")
        return "第二次成功"

    monkeypatch.setattr(w, "_run_step", flaky)
    retried = w.run("retry")
    assert retried["ok"] is True
    assert retried["results"][0]["attempts"] == 2
    assert retried["results"][0]["result"] == "第二次成功"
    now = time.localtime()
    ticked = w.tick(now)
    assert ticked["ran"] == ["scheduled"]
    assert w.tick(now)["ran"] == []


def test_workflow_runner_lifecycle_and_async_cancel(tmp_path):
    _write_workflow(tmp_path, "slow", """
name: 慢任务
steps:
  - name: 等待
    action: wait
    seconds: 5
""")
    w = WorkflowRunner(_Trunk(tmp_path))
    started = w.start()
    assert started["ok"] is True and w.health()["stage"] == "started"
    assert w.start("slow")["ok"] is True
    time.sleep(0.1)
    assert w.status()["running"] is True
    w.stop()
    time.sleep(0.05)
    status = w.status()
    assert status["running"] is False
    assert status["last"]["cancelled"] is True
    assert w.health()["stage"] == "stopped"
    assert w.status()["lifecycle"]["stage"] == "stopped"


class _FakeLLM:
    def __init__(self, reply="分析结果"):
        self.reply = reply
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages)
        return self.reply


class _FakeSearch:
    def search(self, query):
        return {"结果": [{"标题": "资料", "摘要": "关于 " + str(query)}]}


class _FakeRunner:
    def __init__(self, fail=False):
        self.fail = fail
        self.timeout = 10
        self.calls = 0

    def run_code(self, code):
        self.calls += 1
        if self.fail:
            return {"成功": False, "错误": "boom", "stderr": "boom"}
        return {"成功": True, "stdout": "ok", "stderr": ""}


def test_agent_analyst_compare_and_evidence(tmp_path):
    t = _Trunk(tmp_path)
    t.modules.update({"llm": _FakeLLM(), "deep_search": _FakeSearch()})
    agent = AgentAnalyst(t)
    result = agent.compare("转化率 12%", "转化率 18%", "成本,风险")
    assert result["ok"] is True
    assert result["数据对比"][0]["差值"] == 6
    assert "50.0%" in result["数据对比"][0]["变化率"]
    assert "资料" in result["证据"]
    assert result["风险"]
    analyzed = agent.analyze("是否上线新功能", baseline="当前版本")
    assert analyzed["ok"] is True and analyzed["分析"]
    assert analyzed["llm"] is True
    assert agent.analyze("")["error"]["code"] == "PLUGIN_MISSING_ARG"
    no_llm = AgentAnalyst(t)
    t.modules.pop("llm")
    offline = no_llm.analyze("没有模型时")
    assert offline["ok"] is True and offline["llm"] is False


def test_agent_coder_solve_sandbox_and_review(tmp_path):
    t = _Trunk(tmp_path)
    t.modules.update({
        "llm": _FakeLLM("```python\nprint('hi')\n```"),
        "code_runner": _FakeRunner(),
    })
    agent = AgentCoder(t)
    solved = agent.solve("打印 hi")
    assert solved["ok"] is True and solved["运行成功"] is True
    assert "print('hi')" in solved["代码"]
    run = agent.run_code("print(1)")
    assert run["ok"] is True and run["运行成功"] is True
    review = agent.review("def broken(")
    assert review["ok"] is True
    assert any("语法错误" in issue for issue in review["问题"])
    t.modules["code_runner"] = _FakeRunner(fail=True)
    bad = agent.solve("打印 hi")
    assert bad["ok"] is True and bad["运行成功"] is False
    assert bad["轮次"] == 3
    assert agent.solve("")["error"]["code"] == "PLUGIN_MISSING_ARG"


def test_agent_planner_plan_workflow_and_next(tmp_path):
    plan_json = json.dumps([
        {"id": "s1", "title": "确认目标", "action": "set",
         "args": {"value": "目标"}, "depends_on": [], "done_when": "清楚"},
        {"id": "s2", "title": "收集资料", "action": "search",
         "args": {"query": "资料"}, "depends_on": ["s1"],
         "done_when": "有资料"},
    ], ensure_ascii=False)
    t = _Trunk(tmp_path)
    t.modules["llm"] = _FakeLLM(plan_json)
    agent = AgentPlanner(t)
    planned = agent.plan("做一个测试计划")
    assert planned["ok"] is True and planned["llm"] is True
    assert [s["id"] for s in planned["步骤"]] == ["s1", "s2"]
    written = agent.plan_to_workflow("做一个测试计划", name="plan_test")
    assert written["ok"] is True and written["文件"].endswith("plan_test.yaml")
    loaded = WorkflowRunner(t).load("plan_test")
    assert loaded and len(loaded["steps"]) == 2
    assert loaded["steps"][1]["query"] == "资料"
    assert agent.plan_to_workflow("再做一个", name="plan_test")["ok"] is False
    ready = agent.next_steps(plan_json, "s1")
    assert ready["可执行"] == ["s2"]
    assert ready["阻塞"] == []
    fallback_agent = AgentPlanner(_Trunk(tmp_path))
    fallback = fallback_agent.plan("没有模型")
    assert fallback["ok"] is True and fallback["llm"] is False
    assert len(fallback["步骤"]) >= 3
    assert agent.plan("")["error"]["code"] == "PLUGIN_MISSING_ARG"
