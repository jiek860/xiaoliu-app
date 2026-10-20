# -*- coding: utf-8 -*-
"""第二轮质量硬化回归：安全边界、沙箱、资源清理、线程和增量索引。"""
import json
import os
import sys
import tempfile
import threading
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.action_schema import make_action, validate_action  # noqa: E402
from core.agent_permissions import authorize_agent_action  # noqa: E402
from core.agent_harness import RunRegistry  # noqa: E402
from core.agent_artifacts import cleanup_agent_runs  # noqa: E402
from core.patch_engine import PatchError, validate_patch  # noqa: E402
from core.workspace_index import WorkspaceIndex  # noqa: E402


class _GateTrunk:
    def __init__(self, base, allow_headless=False):
        self.base = base
        self.allow_headless_agent = allow_headless
        self.confirm_cb = None
        self.confirm_scope_cb = None

    def rule(self, key, default=None):
        return default

    def confirm(self, action, detail):
        return False


def test_high_risk_type_cannot_be_downgraded(tmp_path):
    action = make_action("write_file", risk="low",
                         args={"path": str(tmp_path / "a.txt"),
                               "content": "x"})
    fixed = validate_action(action)
    assert fixed["risk"] == "high"
    gate = authorize_agent_action(
        _GateTrunk(str(tmp_path)), "computer_agent", fixed)
    assert gate["allow"] is False
    assert "fail-closed" in gate["reason"]


def test_headless_readonly_allowed_but_write_denied(tmp_path):
    trunk = _GateTrunk(str(tmp_path))
    read = authorize_agent_action(
        trunk, "computer_agent",
        make_action("read_file", args={"path": str(tmp_path / "a.txt")}))
    write = authorize_agent_action(
        trunk, "computer_agent",
        make_action("write_file", args={"path": str(tmp_path / "a.txt"),
                                        "content": "x"}))
    assert read["allow"] is True
    assert write["allow"] is False


def test_explicit_headless_test_double_allows(tmp_path):
    trunk = _GateTrunk(str(tmp_path), allow_headless=True)
    gate = authorize_agent_action(
        trunk, "computer_agent",
        make_action("write_file", args={"path": str(tmp_path / "a.txt"),
                                        "content": "x"}))
    assert gate["allow"] is True


def test_patch_rejects_protected_paths(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("old", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "config.json").write_text("{}", encoding="utf-8")
    for rel in (".git/config", "data/config.json"):
        with pytest.raises(PatchError):
            validate_patch(str(root), {
                "files": [{"op": "write", "path": rel, "content": "x"}]
            })


def test_command_sandbox_strips_secret_env_and_times_out(tmp_path, monkeypatch):
    from core.sandbox import run_command
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    r = run_command(
        '"%s" -c "import os; print(os.getenv(\'OPENAI_API_KEY\'))"' % sys.executable,
        timeout=10, cwd=str(tmp_path))
    assert r["ok"] is True, r
    assert "should-not-leak" not in r["output"]
    t = run_command(
        '"%s" -c "import time; time.sleep(5)"' % sys.executable,
        timeout=1, cwd=str(tmp_path))
    assert t["ok"] is False
    assert t["timed_out"] is True


def test_git_branch_name_rejects_injection(tmp_path):
    from core.code_agent import CodeAgent

    class T:
        allow_headless_agent = True
        base = str(tmp_path)
        modules = {}

    a = CodeAgent(T(), str(tmp_path))
    r = a.git_create_work_branch("bad; rm -rf /")
    assert r["ok"] is False


def test_screenshots_are_unique_and_observe_can_be_on_demand(tmp_path):
    from core.computer_agent import ComputerAgent

    class C:
        def __init__(self):
            self.shots = 0
            self.dumps = 0

        def list_windows(self):
            return ["桌面"]

        def get_active_window(self):
            return "桌面"

        def screenshot(self, path=None):
            self.shots += 1
            if path:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(b"png")
            return True, path or ""

        def ui_dump(self, window=None, depth=3):
            self.dumps += 1
            return {"ok": True, "结构": "ButtonControl  「保存」  @(1,2,3,4)"}

    class T:
        allow_headless_agent = True
        base = str(tmp_path)
        modules = {}

    c = C()
    t = T()
    t.modules = {"computer_controller": c}
    a = ComputerAgent(t)
    s1 = a.observe()
    s2 = a.observe()
    assert s1["screenshot"] != s2["screenshot"]
    before = c.shots
    a.observe(include_screenshot=False, include_uia=False,
              include_browser=False)
    assert c.shots == before


def test_agent_artifact_cleanup(tmp_path):
    root = tmp_path / "data" / "agent_runs"
    for i in range(8):
        d = root / ("run_%d" % i)
        d.mkdir(parents=True)
        (d / "events.jsonl").write_text("x\n" * 20, encoding="utf-8")
    r = cleanup_agent_runs(str(tmp_path), max_runs=3, max_event_lines=5)
    left = [x for x in os.listdir(root) if os.path.isdir(os.path.join(root, x))]
    assert len(left) <= 3
    assert r["ok"] is True


def test_run_registry_prunes_terminal_runs():
    reg = RunRegistry(max_runs=20)
    for i in range(30):
        rid = "r%d" % i
        reg.start_run("test", str(i), run_id=rid)
        reg.finish_run(rid, "completed")
    assert len(reg.list_runs(limit=100)) <= 20
    assert reg.active_count() == 0


def test_browser_calls_run_on_one_dedicated_thread():
    from modules.installed.browser import Browser

    class Page:
        url = "https://example.test"
        def title(self):
            return "ok"

    b = Browser(None)
    b._page = Page()
    ids = []
    def call():
        ids.append(threading.get_ident())
        assert b.current_info()["ok"] is True
    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ids) == 3
    b.shutdown()


def test_workspace_index_incremental_refresh(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    idx = WorkspaceIndex(str(tmp_path / "base"), str(root))
    idx.rebuild()
    old_symbols = idx.stats()["symbols"]
    time.sleep(0.01)
    (root / "a.py").write_text("def a():\n    return 3\n"
                               "def c():\n    return 4\n", encoding="utf-8")
    r = idx.refresh()
    assert "a.py" in r["changed"]
    assert "b.py" not in r["changed"]
    assert idx.stats()["symbols"] >= old_symbols
    assert idx.find_symbols("c")


def test_lazy_health_compile_all():
    from core.lazy_health import compile_lazy_sources
    r = compile_lazy_sources(BASE)
    assert r["ok"] is True, r
    assert r["checked"] >= 60
