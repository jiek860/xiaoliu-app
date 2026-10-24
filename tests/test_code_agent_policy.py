# -*- coding: utf-8 -*-
"""代码 Agent 轮次策略、终止条件与多文件 dry-run 测试。"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code_agent_policy import (  # noqa: E402
    DEFAULT_MAX_ROUNDS, MAX_MAX_ROUNDS, evaluate_round, failure_fingerprint,
    resolve_max_rounds,
)
from core.patch_engine import (  # noqa: E402
    PatchError, apply_patch, dry_run_patch,
)


class _CfgTrunk:
    def __init__(self, config):
        self.config = config


def test_round_limit_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("X6_CODE_AGENT_MAX_ROUNDS", raising=False)
    assert resolve_max_rounds(None, _CfgTrunk({})) == DEFAULT_MAX_ROUNDS
    assert resolve_max_rounds(0) == 1
    assert resolve_max_rounds(999) == MAX_MAX_ROUNDS
    assert resolve_max_rounds(7) == 7


def test_round_limit_env_and_config_precedence(monkeypatch):
    monkeypatch.setenv("X6_CODE_AGENT_MAX_ROUNDS", "10")
    assert resolve_max_rounds(None, _CfgTrunk({"code_max_rounds": 4})) == 10
    assert resolve_max_rounds(5, _CfgTrunk({})) == 5
    monkeypatch.delenv("X6_CODE_AGENT_MAX_ROUNDS", raising=False)
    assert resolve_max_rounds(None, _CfgTrunk({"code_max_rounds": 8})) == 8
    assert resolve_max_rounds(
        None, _CfgTrunk({"code_agent": {"max_rounds": 3}})) == 3


def test_evaluate_round_stops_when_green():
    v = evaluate_round(round_no=1, max_rounds=12,
                       tests={"ok": True}, lint={"ok": True})
    assert v["stop"] is True and v["reason"] == "tests_green"


def test_evaluate_round_detects_no_new_error():
    tests = {"ok": False, "results": [{"ok": False, "output": "E   assert 1 == 2"}]}
    first = evaluate_round(round_no=1, max_rounds=12, tests=tests, lint={"ok": True},
                           fingerprint_history=[], patch_history=[])
    assert first["stop"] is False
    second = evaluate_round(round_no=2, max_rounds=12, tests=tests, lint={"ok": True},
                            fingerprint_history=[first["fingerprint"]],
                            patch_history=["p1"], patch_id="p2")
    assert second["stop"] is True and second["reason"] == "no_progress"


def test_evaluate_round_same_patch_same_error_stops():
    tests = {"ok": False, "results": [{"ok": False, "output": "boom"}]}
    v = evaluate_round(round_no=2, max_rounds=12, tests=tests, lint={"ok": True},
                       fingerprint_history=[failure_fingerprint("boom")],
                       patch_history=["p1"], patch_id="p1")
    assert v["stop"] is True and v["reason"] == "no_progress"


def test_evaluate_round_max_rounds():
    tests = {"ok": False, "results": [{"ok": False, "output": "new error"}]}
    v = evaluate_round(round_no=3, max_rounds=3, tests=tests, lint={"ok": True},
                       fingerprint_history=["deadbeef"])
    assert v["stop"] is True and v["reason"] == "max_rounds"


def _two_file_patch(broken=False):
    content = "def ok():\n    return 1\n"
    if broken:
        content = "def broken(:\n    pass\n"
    return {"goal": "两文件", "files": [
        {"path": "a.py", "hunks": [{"old": "x = 1", "new": "x = 2"}]},
        {"path": "b.py", "op": "create", "content": content},
    ]}


def test_dry_run_blocks_batch_before_any_write(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    dry = dry_run_patch(str(root), _two_file_patch(broken=True))
    assert dry["ok"] is False
    assert any("b.py" in e for e in dry["errors"])
    with pytest.raises(PatchError):
        apply_patch(str(root), _two_file_patch(broken=True))
    assert (root / "a.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (root / "b.py").exists()


def test_dry_run_ok_then_apply(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    dry = dry_run_patch(str(root), _two_file_patch())
    assert dry["ok"] is True
    assert {f["path"] for f in dry["files"]} == {"a.py", "b.py"}
    r = apply_patch(str(root), _two_file_patch())
    assert r["ok"] is True
    assert "x = 2" in (root / "a.py").read_text(encoding="utf-8")
    assert (root / "b.py").exists()
