# -*- coding: utf-8 -*-
"""第 6 批：行级编辑内核（hunk 形状 / 定位 / 预演 / 3-way / 逐段撤销 / 作用域）。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import hunk_edit as he  # noqa: E402
from core import patch_engine as pe  # noqa: E402
from core import patch_protocol as pp  # noqa: E402
from core.code_agent_policy import scope_gate, scope_mode  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}

    def rule(self, name, default=None):
        return self.rules.get(name, default)


class FakeAgent:
    def __init__(self, rules=None):
        self.trunk = FakeTrunk(rules)
        self.events = []

    def _emit(self, kind, payload):
        self.events.append((kind, payload))


def _write(root, rel, text):
    p = os.path.join(str(root), rel)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


# ---------------------------------------------------------------- 形状
def test_hunk_from_range_cuts_old_and_keeps_context():
    text = "a\nb\nc\nd\ne\n"
    h = he.hunk_from_range(text, 3, 3, "C\n", context=1)
    assert h["old"] == "b\nc\nd\n"
    assert h["new"] == "b\nC\nd\n"
    assert h["start_line"] == 3


def test_hunk_from_range_clamps_and_adds_newline():
    h = he.hunk_from_range("x = 1\n", 99, 120, "x = 2")
    assert h["old"] == "x = 1\n"
    assert h["new"] == "x = 2\n"


def test_range_hunk_needs_file_text_for_normalize():
    try:
        he.normalize_hunk({"start": 1, "end": 1, "new": "y\n"})
        assert False, "缺文件内容应当报错"
    except ValueError as e:
        assert "文件内容" in str(e)


def test_normalize_fragment_hunk_keeps_old():
    item = he.normalize_hunk({"old": "x = 1\n", "new": "x = 2\n", "reason": "改值"})
    assert item["old"] == "x = 1\n" and item["reason"] == "改值"


def test_validate_patch_accepts_range_shape(tmp_path):
    _write(tmp_path, "m.py", "a = 1\nb = 2\nc = 3\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"start": 2, "end": 2, "new": "b = 20\n", "context": 1}]}]}
    normalized = pe.validate_patch(str(tmp_path), patch)
    hunk = normalized["files"][0]["hunks"][0]
    assert hunk["old"] == "a = 1\nb = 2\nc = 3\n"
    dry = pe.dry_run_patch(str(tmp_path), patch)
    assert dry["ok"] is True
    assert "b = 20" in pe.unified_diff(str(tmp_path), patch)


def test_validate_patch_rejects_range_without_content(tmp_path):
    _write(tmp_path, "m.py", "a = 1\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"new": "x\n"}]}]}
    try:
        pe.validate_patch(str(tmp_path), patch)
        assert False, "既没有 old 也没有 start/end 应当被拒绝"
    except pe.PatchError as e:
        assert "old" in str(e)


# ---------------------------------------------------------------- 定位
def test_locate_exact_and_line():
    found = he.locate("a\nb\nc\n", {"old": "b\n"})
    assert found["status"] == "exact" and found["line"] == 2


def test_locate_fuzzy_whitespace_tolerates_indent():
    found = he.locate("def f():\n    return 1\n", {"old": "def f():\n  return 1\n"})
    assert found["status"] == "fuzzy_whitespace"


def test_locate_fuzzy_anchor_when_user_edited_middle():
    text = "def f():\n    x = 2   # 用户手改\n    return x\n"
    found = he.locate(text, {"old": "def f():\n    x = 1\n    return x\n"})
    assert found["status"] == "fuzzy_anchor"
    assert found["span"] is not None


def test_locate_duplicate_and_missing():
    assert he.locate("x\nx\n", {"old": "x\n"})["status"] == "duplicate"
    assert he.locate("y\n", {"old": "x\n"})["status"] == "missing"
    assert he.locate("", {"old": ""})["status"] == "missing"


def test_apply_hunk_reports_noop():
    out = he.apply_hunk("x = 1\n", {"old": "x = 1\n", "new": "x = 1\n"})
    assert out["ok"] is True and out["noop"] is True


def test_explain_status_is_chinese():
    assert "精确定位" in he.explain_status("exact")
    assert he.explain_status("不存在") != ""


# ---------------------------------------------------------------- 预演
def test_plan_marks_status_and_summary(tmp_path):
    _write(tmp_path, "m.py", "a = 1\nb = 2\nc = 3\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"start": 1, "end": 1, "new": "a = 10\n", "context": 1},
        {"old": "zzz\n", "new": "b = 20\n"}]}]}
    result = he.plan(str(tmp_path), patch)
    assert result["ok"] is False
    assert result["hunks"][0]["status"] == "exact"
    assert result["hunks"][1]["status"] == "missing"
    assert "可应用" in he.summary(result)


def test_plan_skip_marks_not_applied(tmp_path):
    _write(tmp_path, "m.py", "a = 1\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "a = 1\n", "new": "a = 2\n"}]}]}
    result = he.plan(str(tmp_path), patch, selected_hunks=set())
    assert result["ok"] is True
    assert result["hunks"][0]["skipped"] is True


def test_plan_missing_file_is_error(tmp_path):
    result = he.plan(str(tmp_path), {"files": [{"path": "nope.py", "op": "update",
                                              "hunks": [{"old": "x\n", "new": "y\n"}]}]})
    assert result["ok"] is False


# ---------------------------------------------------------------- 3-way
def test_three_way_clean_when_untouched():
    base = "a\nb\nc\n"
    report = he.three_way(base, base, {"old": "b\n", "new": "B\n"})
    assert report["status"] == "clean"
    assert "B" in report["options"]["use_ai"]


def test_three_way_clean_when_user_edited_elsewhere():
    base = "a\nb\nc\n"
    ours = "a\nb\nc\nd\n"
    report = he.three_way(base, ours, {"old": "b\n", "new": "B\n"})
    assert report["status"] == "clean"
    assert report["options"]["keep_mine"] == ours


def test_three_way_conflict_when_same_block_edited():
    base = "a\nb\nc\n"
    ours = "a\nb_user\nc\n"
    report = he.three_way(base, ours, {"old": "b\n", "new": "B\n"})
    assert report["status"] == "conflict"
    assert set(report["options"]) >= set(he.CONFLICT_OPTIONS)
    assert report["options"]["keep_mine"] == ours


def test_three_way_stale_when_base_missing():
    report = he.three_way("x\n", "x\n", {"old": "zzz\n", "new": "y\n"})
    assert report["status"] == "stale"


def test_conflict_report_lists_only_conflicts(tmp_path):
    _write(tmp_path, "m.py", "a\nb_user\nc\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "b\n", "new": "B\n"}]}]}
    rows = he.conflict_report(str(tmp_path), patch, {"m.py": "a\nb\nc\n"})
    assert rows and rows[0]["key"] == "m.py:0"


# ---------------------------------------------------------------- 应用/撤销
def test_apply_hunks_writes_and_undo_restores(tmp_path):
    _write(tmp_path, "m.py", "a = 1\nb = 2\n")
    patch = {"patch_id": "p1", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "a = 1\n", "new": "a = 10\n"},
        {"old": "b = 2\n", "new": "b = 20\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch)
    assert r["ok"] is True and r["applied"] == ["m.py"]
    text = open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read()
    assert "a = 10" in text and "b = 20" in text
    assert os.path.isfile(r["manifest"])
    points = he.list_undo_points(r["manifest"])
    assert len(points) == 2
    back = he.undo_hunk(r["manifest"], "m.py", 0)
    assert back["ok"] is True
    text = open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read()
    assert text == "a = 1\nb = 2\n"


def test_apply_hunks_respects_selected(tmp_path):
    _write(tmp_path, "m.py", "a = 1\nb = 2\n")
    patch = {"patch_id": "p2", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "a = 1\n", "new": "a = 10\n"},
        {"old": "b = 2\n", "new": "b = 20\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch, selected_hunks={"m.py:1"})
    text = open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read()
    assert r["ok"] is True and "a = 1" in text and "b = 20" in text


def test_apply_hunks_reports_missing_hunk(tmp_path):
    _write(tmp_path, "m.py", "a = 1\n")
    patch = {"patch_id": "p3", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "zzz\n", "new": "y\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch)
    assert r["ok"] is False
    assert any("没找到" in e for e in r["errors"])


def test_apply_hunks_conflict_policy_block(tmp_path):
    _write(tmp_path, "m.py", "a\nb_user\nc\n")
    patch = {"patch_id": "p4", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "b\n", "new": "B\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch, base_texts={"m.py": "a\nb\nc\n"},
                       conflict_policy="block")
    assert r["ok"] is False and r["conflicts"]
    text = open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read()
    assert "b_user" in text


def test_apply_hunks_delegates_create(tmp_path):
    patch = {"patch_id": "p5", "files": [
        {"path": "new.py", "op": "create", "content": "x = 1\n"}]}
    r = he.apply_hunks(str(tmp_path), patch)
    assert r["ok"] is True and r["applied"] == ["new.py"]


def test_undo_all_restores_everything(tmp_path):
    _write(tmp_path, "m.py", "a = 1\n")
    patch = {"patch_id": "p6", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "a = 1\n", "new": "a = 2\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch)
    out = he.undo_all(r["manifest"])
    assert out["restored"] == ["m.py"]
    assert open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read() == "a = 1\n"


def test_undo_hunk_without_manifest_is_error(tmp_path):
    bad = os.path.join(str(tmp_path), "nope.json")
    assert he.undo_hunk(bad, "m.py", 0)["ok"] is False
    assert he.list_undo_points(bad) == []


# ---------------------------------------------------------------- 作用域
def test_scope_guard_flags_out_of_scope():
    patch = {"files": [{"path": "other/b.py", "op": "create", "content": "x\n"}]}
    r = he.scope_guard(patch, ["core/hunk_edit.py"])
    assert r["requires_approval"] is True
    assert r["violations"][0]["path"] == "other/b.py"


def test_scope_guard_allows_prefix_and_empty_allowlist():
    patch = {"files": [{"path": "tests/test_x.py", "op": "create", "content": "x\n"}]}
    assert he.scope_guard(patch, ["tests"])["ok"] is True
    assert he.scope_guard(patch, [])["ok"] is True


def test_scope_guard_strict_blocks():
    patch = {"files": [{"path": "other/b.py", "op": "create", "content": "x\n"}]}
    r = he.scope_guard(patch, ["core"], strict=True)
    assert r["blocked"] is True and r["ok"] is False


def test_scope_gate_modes():
    agent = FakeAgent()
    patch = {"files": [{"path": "other/b.py", "op": "create", "content": "x\n"}]}
    gate = scope_gate(agent, patch, ["core"])
    assert gate["mode"] == "ask"
    assert gate["requires_approval"] is True and gate["blocked"] is False
    assert agent.events and agent.events[0][0] == "scope"

    strict = scope_gate(FakeAgent({"code.改动范围": "strict"}), patch, ["core"])
    assert strict["blocked"] is True

    off = scope_gate(FakeAgent({"code.改动范围": "off"}), patch, ["core"])
    assert off["ok"] is True and off["violations"] == []

    assert scope_mode(FakeAgent({"code.改动范围": "bogus"})) == "ask"


# ---------------------------------------------------------------- 协议联动
def test_review_exposes_hunk_plan(tmp_path):
    _write(tmp_path, "m.py", "value = 1\n")
    report = pp.review(str(tmp_path), {"files": [{
        "path": "m.py", "op": "update",
        "hunks": [{"old": "value = 1\n", "new": "value = 2\n"}]}]}, FakeTrunk())
    assert report["ok"] is True
    assert report["hunks"][0]["status"] == "exact"
    assert "1 个 hunk" in report["hunk_summary"]


def test_changed_lines_counts_range_hunk():
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"start": 3, "end": 6, "new": "x\n"}]}]}
    assert pp.changed_lines(patch) >= 4


def test_apply_patch_accepts_range_hunk(tmp_path):
    _write(tmp_path, "m.py", "a = 1\nb = 2\n")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"start": 2, "end": 2, "new": "b = 20\n", "context": 1}]}]}
    r = pe.apply_patch(str(tmp_path), patch)
    assert r["ok"] is True
    text = open(os.path.join(str(tmp_path), "m.py"), encoding="utf-8").read()
    assert "b = 20" in text and "a = 1" in text


def test_saved_manifest_is_json(tmp_path):
    _write(tmp_path, "m.py", "a = 1\n")
    patch = {"patch_id": "p7", "files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "a = 1\n", "new": "a = 2\n"}]}]}
    r = he.apply_hunks(str(tmp_path), patch)
    data = json.load(open(r["manifest"], encoding="utf-8"))
    assert data["patch_id"] == "p7"
    assert data["files"][0]["hunks"][0]["status"] == "exact"
