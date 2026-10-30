# -*- coding: utf-8 -*-
"""批次 46.3：PatchV2 协议（局部优先、禁整文件覆盖、语法/最小性、风险分级）。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import patch_protocol as pp  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = rules or {}

    def rule(self, name, default=None):
        return self.rules.get(name, default)


def _update(rel="m.py", old="value = 1\n", new="value = 2\n"):
    return {"files": [{"path": rel, "op": "update",
                       "hunks": [{"old": old, "new": new}]}]}


def test_mode_defaults_to_shadow():
    assert pp.mode(FakeTrunk()) == "shadow"
    assert pp.mode(FakeTrunk({"code.patch_v2": "on"})) == "on"
    assert pp.mode(FakeTrunk({"code.patch_v2": "bogus"})) == "shadow"


def test_update_passes_and_is_medium(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    report = pp.review(str(tmp_path), _update(), FakeTrunk())
    assert report["ok"] is True
    assert report["risk"]["level"] == "medium"
    assert report["normalized"]["files"][0]["op"] == "update"


def test_write_on_existing_file_is_rejected(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    patch = {"files": [{"op": "write", "path": "m.py", "content": "value = 2\n"}]}
    report = pp.review(str(tmp_path), patch, FakeTrunk())
    assert report["ok"] is False
    assert any("禁止 write" in e for e in report["errors"])


def test_create_new_file_is_low_risk(tmp_path):
    patch = {"files": [{"op": "create", "path": "new_mod.py",
                        "content": "def helper():\n    return 1\n"}]}
    report = pp.review(str(tmp_path), patch, FakeTrunk())
    assert report["ok"] is True
    assert report["risk"]["level"] == "low"


def test_delete_or_rename_is_high_risk(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    from core.patch_engine import validate_patch
    normalized = validate_patch(str(tmp_path), {
        "files": [{"op": "rename", "path": "a.py", "new_path": "b.py"}]})
    risk = pp.classify_patch(str(tmp_path), normalized)
    assert risk["level"] == "high"
    assert any("重命名" in r for r in risk["reasons"])


def test_config_change_is_high_risk(tmp_path):
    (tmp_path / "requirements.txt").write_text("a\n", encoding="utf-8")
    patch = {"files": [{"op": "update", "path": "requirements.txt",
                        "hunks": [{"old": "a\n", "new": "b\n"}]}]}
    report = pp.review(str(tmp_path), patch, FakeTrunk())
    assert report["risk"]["level"] == "high"
    assert any("配置" in r for r in report["risk"]["reasons"])


def test_many_files_is_high_risk(tmp_path):
    patch = {"files": []}
    for i in range(3):
        patch["files"].append({"op": "create", "path": "n%d.py" % i,
                               "content": "x = %d\n" % i})
    report = pp.review(str(tmp_path), patch, FakeTrunk())
    assert report["risk"]["level"] == "high"


def test_too_many_lines_is_rejected(tmp_path):
    (tmp_path / "m.py").write_text("a\nb\n", encoding="utf-8")
    old = "\n".join("l%d" % i for i in range(160)) + "\n"
    new = "\n".join("m%d" % i for i in range(160)) + "\n"
    (tmp_path / "m.py").write_text(old, encoding="utf-8")
    report = pp.review(str(tmp_path), {
        "files": [{"op": "update", "path": "m.py",
                   "hunks": [{"old": old, "new": new}]}]}, FakeTrunk())
    assert report["ok"] is False
    assert any("超过" in e for e in report["errors"])


def test_syntax_error_is_caught(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    report = pp.review(str(tmp_path), _update(new="def broken(:\n"), FakeTrunk())
    assert report["ok"] is False
    assert any("语法错误" in e for e in report["errors"])


def test_compile_check_ok(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    checked = pp.compile_check(str(tmp_path), pp.review(
        str(tmp_path), _update(), FakeTrunk())["normalized"])
    assert checked["ok"] is True


def test_anchor_warning_when_line_drifts(tmp_path):
    (tmp_path / "m.py").write_text("\n" * 20 + "value = 1\n", encoding="utf-8")
    patch = {"files": [{"path": "m.py", "op": "update", "hunks": [
        {"old": "value = 1", "new": "value = 2", "line": 2}]}]}
    report = pp.review(str(tmp_path), patch, FakeTrunk())
    assert report["ok"] is True
    assert any("锚点" in w for w in report["warnings"])


def test_forbidden_path_blocks(tmp_path):
    patch = {"files": [{"op": "create", "path": "data/x.py", "content": "x=1\n"}]}
    from core.patch_engine import PatchError
    try:
        pp.review(str(tmp_path), patch, FakeTrunk())
        assert False, "受保护路径应当被拒绝"
    except PatchError:
        pass
    risk = pp.classify_patch(str(tmp_path), patch)
    assert risk["level"] == "forbidden"


def test_function_span_inside_function_and_class():
    code = ("import os\n\n@deco\n"
            "def outer():\n    return 1\n\n"
            "class A:\n    def method(self):\n        pass\n")
    span = pp.function_span(code, 4)
    assert span == {"start": 3, "end": 5, "name": "outer"}
    span = pp.function_span(code, 9)
    assert span["name"] == "method"


def test_function_span_syntax_error_returns_none():
    assert pp.function_span("def broken(:\n", 1) is None


def test_minimal_hunks_only_changed_lines():
    old = "a\nb\nc\nd\n"
    new = "a\nB\nc\nd\n"
    hunks = pp.minimal_hunks(old, new)
    assert len(hunks) == 1
    assert hunks[0]["old"] != hunks[0]["new"]
    assert "B" in hunks[0]["new"]
    assert "b\n" in hunks[0]["old"]
    assert pp.minimal_hunks(old, old) == []


def test_record_edit_writes_jsonl(tmp_path):
    path = pp.record_edit(str(tmp_path), {"path": "m.py", "mode": "function"})
    assert os.path.isfile(path)
    row = json.loads(open(path, encoding="utf-8").read().strip())
    assert row["path"] == "m.py" and row["mode"] == "function"


def test_switches_default_off():
    trunk = FakeTrunk()
    assert pp.auto_apply_enabled(trunk) is False
    assert pp.background_enabled(trunk) is False
    assert pp.verify_mode(trunk) == "off"


def test_locate_failures_default_on_and_lint_extra_default_shadow():
    """批次 D9：失败定位默认参与回修提示；ruff/mypy 只影子记录。"""
    trunk = FakeTrunk()
    assert pp.locate_mode(trunk) == "on"
    assert pp.lint_extra_mode(trunk) == "shadow"
    assert pp.locate_mode(FakeTrunk({"code.locate_failures": "off"})) == "off"
    assert pp.lint_extra_mode(
        FakeTrunk({"code.lint_extra": "on"})) == "on"
    # 认不出的值按各自默认回退，不把链路卡死
    assert pp.locate_mode(FakeTrunk({"code.locate_failures": "bogus"})) == "on"
    assert pp.lint_extra_mode(
        FakeTrunk({"code.lint_extra": "bogus"})) == "shadow"
