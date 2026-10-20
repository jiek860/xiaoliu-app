# -*- coding: utf-8 -*-
"""四阶段优化模块的回归测试。"""
import json
import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


class _FakeLLM:
    def chat(self, *a, **k):
        return "fake answer"


class _FakeTrunk:
    def __init__(self, base=None):
        self.base = base or tempfile.mkdtemp(prefix="x6opt_")
        self.config = {"security": {"network_mode": "standard"}}
        self.modules = {"llm": _FakeLLM()}
        self.confirm_cb = None

    def call(self, mod, method, *a, **k):
        if mod == "task_planner" and method == "plan":
            return {"步骤": [{"name": "分析"}, {"name": "总结"}]}
        return {"ok": True, "结果": "ok"}

    def rule(self, key, default=False):
        return default

    def _log(self, msg, level="INFO"):
        pass


def test_audit_log_redacts_secret():
    from core.audit_log import AuditLog
    base = tempfile.mkdtemp(prefix="x6audit_")
    a = AuditLog(base)
    a.append({"subject": "x", "args_preview": "token=abcdef123456"})
    rec = a.list_recent(1)[0]
    assert "abcdef123456" not in json.dumps(rec, ensure_ascii=False)


def test_permission_center_lockdown_blocks_dangerous():
    from core.permission_center import PermissionCenter
    t = _FakeTrunk()
    pc = PermissionCenter(t)
    pc.lockdown(True)
    d = pc.authorize("code_run", info={"confirm": True, "danger": True}, args={})
    assert not d["allow"] and not d["requires_confirm"]


def test_net_guard_blocks_private_and_file():
    from core.net_guard import NetGuard
    ng = NetGuard(None)
    assert not ng.check("http://127.0.0.1:1234/x", module="t",
                        purpose="web")["allow"]
    assert not ng.check("file:///C:/Windows/win.ini", module="t",
                        purpose="web")["allow"]
    assert ng.check("https://open.bigmodel.cn/x", module="t",
                    purpose="cloud_model")["allow"]
    assert ng.check("http://127.0.0.1:11434/api/tags", module="llm",
                    purpose="local_model")["allow"]


def test_sandbox_runs_and_times_out():
    from core.sandbox import run_python
    r = run_python("print(1+1)", timeout=5)
    assert r["ok"] and "2" in r["stdout"]
    r2 = run_python("import time; time.sleep(5)", timeout=0.3)
    assert r2["timed_out"]


def test_task_runtime_create_plan_and_run():
    from core.task_runtime import TaskRuntime
    t = _FakeTrunk()
    rt = TaskRuntime(t)
    task = rt.create("测试目标")
    rt.plan(task["id"])
    r = rt.start(task["id"])
    assert r.get("ok")
    deadline = time.time() + 10
    while time.time() < deadline:
        task = rt.get_task(task["id"])
        if task.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert task["status"] == "completed", task
    assert len(task["steps"]) >= 1


def test_diff_review_generates_unified_diff():
    from core.diff_review import preview_edit
    base = tempfile.mkdtemp(prefix="x6diff_")
    p = os.path.join(base, "a.txt")
    open(p, "w", encoding="utf-8").write("a\nb\n")
    r = preview_edit(p, "b", "c")
    assert "-b" in r["diff"] and "+c" in r["diff"]


def test_document_parser_and_retrieval():
    from core.document_parser import parse, chunk_text
    from core.retrieval import HybridRetriever
    r = parse(os.path.join(BASE, "README.md"))
    assert r["ok"] and r["text"]
    chunks = chunk_text(r["text"], chunk_size=100, overlap=20)
    assert chunks
    idx = HybridRetriever(tempfile.mkdtemp(prefix="x6ret_"))
    idx.add("小6 是一个桌面智能体", source="test.md")
    hits = idx.search("小6", top_k=3)
    assert hits


def test_memory_manager_and_workspace():
    from core.memory_manager import MemoryManager
    from core.workspace import Workspace
    base = tempfile.mkdtemp(prefix="x6mem_")
    mm = MemoryManager(_FakeTrunk(base))
    rec = mm.add("记住测试", source="test")
    assert mm.edit(rec["id"], text="记住测试2")["ok"]
    assert mm.search("测试2")
    assert mm.forget(rec["id"])["ok"]
    expired = mm.add("短期记忆", expires_at=time.time() - 1)
    assert all(x.get("id") != expired["id"] for x in mm.list())
    assert mm.purge_expired()["removed"] >= 1
    w = Workspace(None, "ws_test")
    assert os.path.isdir(w.root)
    assert os.path.basename(w.path("..", "x.txt")) == "x.txt"


def test_usage_and_plugin_governance_and_model_registry():
    from core.usage_tracker import UsageTracker
    from core.plugin_governance import PluginGovernance
    from core.model_registry import ModelRegistry
    base = tempfile.mkdtemp(prefix="x6usage_")
    ut = UsageTracker(base)
    ut.record(kind="llm", model="m", tokens_in=10, tokens_out=20)
    s = ut.summary()
    assert s["calls"] == 1 and s["tokens_in"] == 10
    gi = PluginGovernance(base).inspect("import subprocess\n", {"signature": "x"})
    assert "execute" in gi["permissions"] and gi["trust"] == "official_signed"
    mr = ModelRegistry(_FakeTrunk(base))
    mr.register("local-a", kind="local")
    assert mr.list()


def test_task_runtime_resume_skips_completed_steps():
    from core.task_runtime import TaskRuntime

    class CountingLLM:
        def __init__(self):
            self.calls = 0
        def chat(self, *a, **k):
            self.calls += 1
            return "ok"

    t = _FakeTrunk()
    t.modules["llm"] = CountingLLM()
    rt = TaskRuntime(t)
    task = rt.create("resume-test")
    rt.plan(task["id"])
    task = rt.get_task(task["id"])
    task["steps"][0]["status"] = "done"
    task["status"] = "paused"
    rt._save(task)
    r = rt.resume(task["id"])
    assert r.get("ok")
    deadline = time.time() + 5
    while time.time() < deadline:
        task = rt.get_task(task["id"])
        if task.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.03)
    assert task["status"] == "completed", task
    assert t.modules["llm"].calls == 1, t.modules["llm"].calls


def test_task_runtime_cancel_is_not_overwritten_by_completion():
    from core.task_runtime import TaskRuntime

    class SlowLLM:
        def chat(self, *a, **k):
            time.sleep(0.3)
            return "late"

    t = _FakeTrunk()
    t.modules["llm"] = SlowLLM()
    rt = TaskRuntime(t)
    task = rt.create("cancel-test")
    rt.plan(task["id"])
    rt.start(task["id"])
    time.sleep(0.05)
    rt.cancel(task["id"])
    time.sleep(0.5)
    task = rt.get_task(task["id"])
    assert task["status"] == "cancelled", task


def test_permission_revoke_session_rule_works():
    from core.permission_center import PermissionCenter
    pc = PermissionCenter(_FakeTrunk())
    r = pc.approve("tool:fs_edit", scope="session")
    assert pc.revoke(r["rule"]["id"]) is True


def test_tool_confirmation_supports_session_scope():
    from modules.installed.tool_caller import ToolCaller
    from core.permission_center import get_permission_center
    t = _FakeTrunk()
    t.confirm_cb = lambda *a: True
    t.confirm_scope_cb = lambda *a: "session"
    tc = ToolCaller(t)
    assert tc._confirm_tool("fs_edit", {"spec": "{}"},
                            tc.tools["fs_edit"]) is True
    rules = get_permission_center(t).list_rules()
    assert any(r.get("subject") == "fs_edit" and r.get("scope") == "session"
               for r in rules)


def test_cloud_stream_applies_masking_and_usage_tracking():
    from core.llm_client import LLMClient
    from core.usage_tracker import UsageTracker
    base = tempfile.mkdtemp(prefix="x6llm_")
    llm = LLMClient.__new__(LLMClient)
    llm.base = base
    llm.trunk = None
    llm.config = {"cloud_url": "https://example.com/chat/completions",
                  "cloud_key": "k", "cloud_model": "m"}
    seen = {"masked": False}

    def mask(msgs):
        seen["masked"] = True
        return msgs

    class Resp:
        def iter_lines(self):
            return [
                b'data: {"choices":[{"delta":{"content":"hi"}}]}',
                b'data: [DONE]',
            ]

    llm._mask_if_enabled = mask
    llm._post = lambda *a, **k: Resp()
    out = llm._try_cloud_stream([{"role": "user", "content": "secret"}])
    assert out == "hi"
    assert seen["masked"] is True
    assert UsageTracker(base).summary()["calls"] >= 1


def test_context_budget_and_response_cache():
    from core.context_budget import trim_messages, estimate_tokens
    from core.response_cache import ResponseCache
    msgs = [{"role": "system", "content": "S" * 1000}]
    for i in range(20):
        msgs.append({"role": "user", "content": "U%d " % i + "x" * 500})
    out = trim_messages(msgs, max_tokens=800, reserve=200)
    assert out and out[0]["role"] == "system"
    assert estimate_tokens(out) <= estimate_tokens(msgs)
    c = ResponseCache(ttl=10)
    c.set("k", "v")
    assert c.get("k") == "v"
    c.clear()
    assert c.get("k") is None


def test_sqlite_fts_index_add_and_search():
    from core.fts_index import FTSIndex
    base = tempfile.mkdtemp(prefix="x6fts_")
    f = FTSIndex(base)
    if not f.ok:
        return
    assert f.add_many([{"text": "小6 智能体 知识库",
                        "doc_id": "d1", "source": "a.md"}]) == 1
    hits = f.search("小6", 3)
    assert hits and hits[0]["doc_id"] == "d1"
    assert f.delete_source("a.md")


def test_tool_schema_and_result_normalization():
    from core.tool_schema import validate_args
    from core.tool_result import normalize
    assert validate_args({"path": "a.txt"}, {"path": "x"})[0] is True
    assert validate_args({"bad": "x"}, {"path": "x"})[0] is False
    assert validate_args({"path": "a\x00b"}, {"path": "x"})[0] is False
    r = normalize({"ok": False, "错误": "boom"})
    assert r["ok"] is False and r["error"] == "boom"


def test_usage_p95_and_model_circuit_breaker():
    from core.usage_tracker import UsageTracker
    from core.llm_client import LLMClient
    base = tempfile.mkdtemp(prefix="x6router_")
    ut = UsageTracker(base)
    for v in (1, 2, 3, 4, 5):
        ut.record(kind="llm", model="m", elapsed=v)
    st = ut.model_stats("m")
    assert st["calls"] == 5 and st["p95"] >= 4
    llm = LLMClient.__new__(LLMClient)
    llm.base = base
    llm.trunk = None
    llm.config = {}
    llm._model_cooldown = {}
    llm._model_fail_counts = {}
    llm._mark_model_failure("m", "boom")
    llm._mark_model_failure("m", "boom")
    assert llm._model_cooling("m") is True
    llm._mark_model_success("m")
    assert llm._model_cooling("m") is False


def test_permission_rule_hit_count_and_scope_update():
    from core.permission_center import PermissionCenter
    base = tempfile.mkdtemp(prefix="x6perm_")
    pc = PermissionCenter(_FakeTrunk(base))
    allowed_dir = os.path.join(base, "docs") + os.sep
    r = pc.approve("fs_edit", scope="always",
                   constraints={"path_prefix": allowed_dir})
    rule_id = r["rule"]["id"]
    spec = json.dumps({"path": os.path.join(allowed_dir, "a.txt"),
                       "old": "a", "new": "b"}, ensure_ascii=False)
    d = pc.authorize("fs_edit", info={"confirm": True},
                     args={"spec": spec})
    assert d["allow"] is True, d
    rule = pc.list_rules()[0]
    assert rule.get("hit_count", 0) >= 1
    rr = pc.update_constraints(
        rule_id, {"path_prefix": os.path.join(base, "other") + os.sep})
    assert rr.get("ok") is True
    d2 = pc.authorize("fs_edit", info={"confirm": True},
                      args={"spec": spec})
    assert d2["allow"] is False


def test_task_runtime_run_sync_and_auto_router():
    from core.task_runtime import TaskRuntime
    from core.trunk import Trunk
    t = _FakeTrunk()
    rt = TaskRuntime(t)
    out = rt.run_sync("整理项目里的重复记忆", timeout=5)
    assert out.get("ok") is True and out.get("结果"), out

    tr = object.__new__(Trunk)
    tr.config = {"task_auto_mode": "auto"}
    assert tr._should_auto_task("帮我整理一下项目里的重复记忆并生成报告") is True
    assert tr._should_auto_task("你好") is False
    tr.config["task_auto_mode"] = "off"
    assert tr._should_auto_task("帮我整理一下项目里的重复记忆并生成报告") is False
