# -*- coding: utf-8 -*-
"""workflow_runner：加载、变量替换、条件、动作、重试、取消、模板与 cron。

这个模块之前一行测试都没有（覆盖率门槛把它算作"新增未覆盖代码"），
下面按「能离线跑、不碰真实模型/搜索/代码执行」的原则把主路径和
失败分支都过一遍：trunk.modules 里放的是假模块。
"""
import json
import os
import sys
import threading
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from modules.installed.workflow_runner import (  # noqa: E402
    WorkflowCancelled, WorkflowError, WorkflowRunner)


class FakeTrunk:
    def __init__(self, base, modules=None):
        self.base = str(base)
        self.modules = dict(modules or {})
        self.calls = []

    def call(self, name, arg="__no__"):
        """模拟 trunk 的懒加载：只认 deep_search，其它名字照样是空。"""
        self.calls.append((name, arg))
        if name == "deep_search":
            self.modules.setdefault(name, FakeSearch())
        return self.modules.get(name)


class FakeLLM:
    def __init__(self, replies=None):
        self.prompts = []
        self.replies = list(replies or ["默认回复"])

    def chat(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "默认回复"


class FakeSearch:
    def search(self, query):
        return [{"title": "结果", "query": query}]


class FakeRunner:
    def __init__(self, result=None):
        self.timeout = 5
        self.codes = []
        self.result = result if result is not None else {"ok": True, "stdout": "1"}

    def run_code(self, code):
        self.codes.append(code)
        return self.result


def _write(tmp_path, name, data):
    path = tmp_path / "data" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _runner(tmp_path, **modules):
    trunk = FakeTrunk(tmp_path, modules)
    return WorkflowRunner(trunk), trunk


def test_loads_builtin_unknown_and_traversal(tmp_path):
    wf, _tr = _runner(tmp_path)
    builtin = wf.load("daily_digest")
    assert builtin["builtin"] is True and len(builtin["steps"]) == 2
    assert wf.load("no_such") is None
    assert "不存在" in wf._last_error
    assert wf.load("../evil") is None
    assert "不合法" in wf._last_error
    assert wf._safe_name("x.json") == "x"
    assert wf._safe_name(" . ") == ""


def test_load_json_and_yaml_files(tmp_path):
    wf, _tr = _runner(tmp_path)
    data = {"name": "demo", "title": "演示",
            "schedule": "* * * * *",
            "steps": ["用字符串写一步",
                      {"name": "第二步", "use": "set", "value": "v",
                       "with": {"extra": 1}}]}
    _write(tmp_path, "demo.json", data)
    loaded = wf.load("demo")
    assert loaded["title"] == "演示"
    assert loaded["steps"][0]["action"] == "llm"
    assert loaded["steps"][1]["action"] == "set"
    assert loaded["steps"][1]["extra"] == 1

    yaml = pytest.importorskip("yaml", reason="没装 PyYAML 就只测 json 分支")
    (tmp_path / "data" / "workflows" / "y.yaml").write_text(
        yaml.safe_dump({"name": "y", "steps": [{"action": "set",
                                                "value": "1"}]},
                       allow_unicode=True), encoding="utf-8")
    assert wf.load("y")["steps"][0]["action"] == "set"


def test_parse_simple_fallback(tmp_path):
    wf, _tr = _runner(tmp_path)
    path = tmp_path / "data" / "workflows" / "p.yaml"
    path.write_text("name: 简易\n# 注释\nschedule: '0 8 * * *'\n"
                    "steps:\n  - name: 第一步\n    action: set\n"
                    "    value: 1\n  - action: wait\n    seconds: 0\n",
                    encoding="utf-8")
    parsed = wf._parse_simple(str(path))
    assert parsed["name"] == "简易"
    assert parsed["schedule"] == "0 8 * * *"
    assert [s["action"] for s in parsed["steps"]] == ["set", "wait"]


def test_normalize_rejects_bad_steps(tmp_path):
    wf, _tr = _runner(tmp_path)
    assert wf._normalize({"steps": []}, "x") is None
    assert "没有 steps" in wf._last_error
    assert wf._normalize({"steps": ["ok", 42]}, "x") is None
    assert "不是字典" in wf._last_error
    assert wf._normalize("不是字典", "x") is None


def test_load_broken_file_reports_error(tmp_path):
    wf, _tr = _runner(tmp_path)
    p = tmp_path / "data" / "workflows" / "bad.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert wf.load("bad") is None
    assert "读取工作流 bad 失败" in wf._last_error


def test_render_value_and_when(tmp_path):
    wf, _tr = _runner(tmp_path)
    ctx = {"input": "科技新闻", "n": "5", "obj": {"a": 1}, "lst": [1, 2],
           "prev": "上一步", "flag": "no"}
    assert wf._render("{{input}} / {obj} / {lst}", ctx) == \
        "科技新闻 / {\"a\": 1} / [1, 2]"
    assert wf._value("{{prev}}", ctx) == "上一步"
    assert wf._value("missing", ctx) == ""

    assert wf._eval_when("", ctx) is True
    assert wf._eval_when("input contains 科技", ctx) is True
    assert wf._eval_when("input 不包含 体育", ctx) is True
    assert wf._eval_when("n > 3", ctx) is True
    assert wf._eval_when("n <= 3", ctx) is False
    assert wf._eval_when("n == 5", ctx) is True
    assert wf._eval_when("n != 5", ctx) is False
    assert wf._eval_when("n > abc", ctx) is False
    assert wf._eval_when("flag", ctx) is False
    assert wf._eval_when("input", ctx) is True


def test_run_set_wait_and_llm(tmp_path):
    llm = FakeLLM(["摘要完成"])
    wf, _tr = _runner(tmp_path, llm=llm)
    _write(tmp_path, "demo.json", {"name": "demo", "steps": [
        {"name": "变量", "action": "set", "value": "你好 {{input}}"},
        {"name": "等一下", "action": "wait", "seconds": 0},
        {"name": "总结", "action": "llm", "prompt": "{{prev}}"},
    ]})
    out = wf.run("demo", input="世界")
    assert out["ok"] is True and out["steps"] == 3
    assert out["context"]["变量"] == "你好 世界"
    assert llm.prompts[0] == "waited"    # {{prev}} 是上一步（wait）的结果
    assert wf.run("demo", input="再来一次")["ok"] is True
    assert wf.get_history()["历史"][-1]["item"].startswith("工作流 demo")


def test_run_search_and_code(tmp_path):
    runner = FakeRunner({"ok": True, "stdout": "42"})
    wf, _tr = _runner(tmp_path, deep_search=FakeSearch(), code_runner=runner)
    _write(tmp_path, "mix.json", {"name": "mix", "steps": [
        {"name": "搜", "action": "search", "query": "{{input}}"},
        {"name": "跑", "action": "code", "code": "print(42)", "timeout": 9},
    ]})
    out = wf.run("mix", input="关键词")
    assert out["ok"] is True
    assert out["results"][0]["result"][0]["query"] == "关键词"
    assert runner.codes == ["print(42)"]
    assert runner.timeout == 5          # timeout 用完要还原

    runner.result = {"ok": False, "error": {"message": "报错了"}}
    out2 = wf.run("mix", input="x")
    assert out2["ok"] is False
    assert out2["failed_step"] == "跑"
    assert "报错了" in out2["error"]["message"]


def test_run_missing_modules_and_args(tmp_path):
    wf, _tr = _runner(tmp_path)
    _write(tmp_path, "nollm.json", {"name": "nollm", "steps": [
        {"name": "总结", "action": "llm", "prompt": "hi"}]})
    out = wf.run("nollm")
    assert out["ok"] is False and "llm 模块不可用" in out["error"]["message"]

    wf2, _tr2 = _runner(tmp_path, llm=FakeLLM(),
                        deep_search=FakeSearch(), code_runner=FakeRunner())
    _write(tmp_path, "empty.json", {"steps": [{"action": "llm", "prompt": " "}]})
    assert "缺少 prompt" in wf2.run("empty")["error"]["message"]
    _write(tmp_path, "q.json", {"steps": [{"action": "search", "query": " "}]})
    assert "缺少 query" in wf2.run("q")["error"]["message"]
    _write(tmp_path, "c.json", {"steps": [{"action": "code", "code": " "}]})
    assert "缺少 code" in wf2.run("c")["error"]["message"]
    _write(tmp_path, "u.json", {"steps": [{"action": "fly"}]})
    assert "未知动作" in wf2.run("u")["error"]["message"]


def test_llm_none_reply_and_wrong_types(tmp_path):
    class NoneLLM:
        def chat(self, prompt):
            return None

    wf, _tr = _runner(tmp_path, llm=NoneLLM())
    _write(tmp_path, "n.json", {"steps": [
        {"name": "a", "action": "llm", "prompt": "x", "retry": "not-a-number",
         "when": "  "}]})
    out = wf.run("n")
    assert out["ok"] is False and "没有返回内容" in out["error"]["message"]


def test_when_skips_step(tmp_path):
    wf, _tr = _runner(tmp_path)
    _write(tmp_path, "skip.json", {"steps": [
        {"name": "跳过", "action": "set", "value": "1",
         "when": "input contains 触发"},
        {"name": "执行", "action": "set", "value": "2"}]})
    out = wf.run("skip", input="不相关")
    assert out["ok"] is True
    assert out["results"][0]["skipped"] is True
    assert out["context"]["跳过"] == ""


def test_on_error_continue_and_retry(tmp_path):
    class Flaky:
        def __init__(self):
            self.n = 0

        def chat(self, prompt):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("第一次失败")
            return "第二次成功"

    flaky = Flaky()
    wf, _tr = _runner(tmp_path, llm=flaky)
    _write(tmp_path, "retry.json", {"steps": [
        {"name": "重试", "action": "llm", "prompt": "x", "retry": 1}]})
    out = wf.run("retry")
    assert out["ok"] is True
    assert out["results"][0]["attempts"] == 2
    assert out["results"][0]["result"] == "第二次成功"

    class Boom:
        def chat(self, prompt):
            raise RuntimeError("炸了")

    wf3, _tr3 = _runner(tmp_path, llm=Boom())
    _write(tmp_path, "cont.json", {"steps": [
        {"name": "失败", "action": "llm", "prompt": "x",
         "on_error": "continue"},
        {"name": "继续", "action": "set", "value": "done"}]})
    out2 = wf3.run("cont")
    assert out2["ok"] is True
    assert out2["context"]["失败"]["ok"] is False
    assert "炸了" in out2["context"]["失败"]["error"]
    assert out2["context"]["继续"] == "done"


def test_cancel_running_workflow(tmp_path):
    wf, _tr = _runner(tmp_path)
    _write(tmp_path, "slow.json", {"steps": [
        {"name": "慢", "action": "wait", "seconds": 30}]})
    started = wf.start_async("slow")
    assert started["ok"] is True
    time.sleep(0.1)
    stopped = wf.stop()
    assert stopped["cancelled"] is True
    assert wf._last_result["cancelled"] is True
    assert wf._last_result["error"]["code"] == "PLUGIN_CANCELLED"
    assert wf._running is False


def test_start_and_status_and_health(tmp_path):
    wf, _tr = _runner(tmp_path)
    started = wf.start()
    assert started["ok"] is True
    assert "daily_digest" in started["workflows"]
    assert sorted(started["templates"]) == sorted(
        ["daily_digest", "research_brief", "code_review"])
    again = wf.ensure_templates()
    assert again["written"] == [] and len(again["existing"]) == 3
    assert len(wf.templates()) == 3

    status = wf.status()
    assert status["ok"] is True and status["running"] is False
    assert status["workflows"] >= 3
    health = wf.health()
    assert health["模块"] == "workflow_runner"


def test_module_falls_back_to_trunk_call(tmp_path):
    trunk = FakeTrunk(tmp_path)
    wf = WorkflowRunner(trunk)
    mod = wf._module("deep_search")
    assert mod is not None and trunk.calls[0][0] == "deep_search"
    assert wf._module("nothing") is None


def test_tick_runs_due_workflow(tmp_path):
    wf, _tr = _runner(tmp_path)
    _write(tmp_path, "every.json", {"name": "every", "schedule": "* * * * *",
                                    "steps": [{"action": "set", "value": "1"}]})
    out = wf.tick()
    assert out["ok"] is True and "every" in out["ran"]
    assert wf.tick()["ran"] == []          # 同一分钟不重复跑
    wf._running = True
    assert wf.tick()["skipped"] == "busy"
    wf._running = False


def test_cron_match_and_fields(tmp_path):
    wf, _tr = _runner(tmp_path)
    assert wf._cron_field("*/15", 30, 0, 59) is True
    assert wf._cron_field("10-20", 15, 0, 59) is True
    assert wf._cron_field("x", 1, 0, 59) is False
    assert wf._cron_match("not cron", time.localtime()) is False
    now = time.localtime()
    assert wf._cron_match("* * * * *", now) is True
    assert wf._cron_match("0 0 1 1 0", now) is False


def test_result_helpers(tmp_path):
    wf, _tr = _runner(tmp_path)
    assert WorkflowRunner._result_failed({"ok": False}) is True
    assert WorkflowRunner._result_failed({"成功": False}) is True
    assert WorkflowRunner._result_failed({"error": "x"}) is True
    assert WorkflowRunner._result_failed("不是字典") is False
    assert WorkflowRunner._result_reason("不是字典") == "步骤返回失败"
    assert WorkflowRunner._result_reason({"error": "坏"}) == "坏"
    assert WorkflowRunner._result_reason({"stderr": "err"}) == "err"
    with pytest.raises(WorkflowError):
        wf._run_step("fly", {}, {})
    wf._cancel.set()
    with pytest.raises(WorkflowCancelled):
        wf._run_step("set", {}, {})
    wf._cancel.clear()


def test_list_workflows_scan_failure(tmp_path, monkeypatch):
    wf, _tr = _runner(tmp_path)
    monkeypatch.setattr(os, "listdir", lambda *a: (_ for _ in ()).throw(
        OSError("没权限")))
    names = wf.list_workflows()
    assert "daily_digest" in names
    assert "扫描工作流目录失败" in wf._last_error


def test_background_thread_flag_reset(tmp_path):
    wf, _tr = _runner(tmp_path)
    _write(tmp_path, "fast.json", {"steps": [{"action": "set", "value": "1"}]})
    t = threading.Thread(target=wf._background_run, args=("fast", None))
    t.start()
    t.join(3)
    assert wf._running is False
