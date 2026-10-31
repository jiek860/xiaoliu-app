# -*- coding: utf-8 -*-
"""core/patch_engine.py 的同名测试：路径安全、校验、预演、应用与回滚。

全部离线执行，只在 tmp_path 里落盘。
"""
import json
import os

import pytest

from core.patch_engine import (
    PatchError,
    apply_patch,
    dry_run_patch,
    file_patch,
    rollback,
    sha256_file,
    sha256_text,
    unified_diff,
    validate_patch,
)


def _write(root, rel, text):
    p = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


def _read(root, rel):
    with open(os.path.join(str(root), rel.replace("/", os.sep)),
              encoding="utf-8") as f:
        return f.read()


def test_sha256_helpers_agree(tmp_path):
    p = _write(tmp_path, "a.txt", "hello")
    assert sha256_text("hello") == sha256_file(p)
    assert len(sha256_text("hello")) == 64


def test_file_patch_builds_update_patch():
    patch = file_patch("a.py", "old", "new", reason="改一下")
    fp = patch["files"][0]
    assert fp["op"] == "update"
    assert fp["path"] == "a.py"
    assert fp["hunks"][0] == {"old": "old", "new": "new", "reason": "改一下"}
    assert patch["patch_id"].startswith("patch_")


@pytest.mark.parametrize("rel", ["../escape.txt", "C:/x.txt",
                                 "a/../../b.txt"])
def test_validate_rejects_path_escape(tmp_path, rel):
    patch = {"files": [{"op": "create", "path": rel, "content": "x"}]}
    with pytest.raises(PatchError):
        validate_patch(str(tmp_path), patch)


def test_validate_normalizes_posix_absolute_to_relative(tmp_path):
    """/etc/passwd 会按相对路径落到工作区内，不会写到系统目录。"""
    patch = {"files": [{"op": "create", "path": "/etc/passwd", "content": "x"}]}
    out = validate_patch(str(tmp_path), patch)
    assert out["files"][0]["path"] == "etc/passwd"


def test_validate_rejects_protected_path(tmp_path):
    patch = {"files": [{"op": "create", "path": "data/x.json",
                        "content": "{}"}]}
    with pytest.raises(PatchError):
        validate_patch(str(tmp_path), patch)


def test_validate_requires_files_key():
    with pytest.raises(PatchError):
        validate_patch(".", {"goal": "缺 files"})


def test_validate_missing_hunk_reports_error(tmp_path):
    _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "不存在的原文", "print(2)")
    with pytest.raises(PatchError) as ei:
        validate_patch(str(tmp_path), patch)
    assert "没找到" in str(ei.value)


def test_validate_duplicate_hunk_reports_error(tmp_path):
    _write(tmp_path, "a.py", "x = 1\nx = 1\n")
    patch = file_patch("a.py", "x = 1", "x = 2")
    with pytest.raises(PatchError) as ei:
        validate_patch(str(tmp_path), patch)
    assert "不唯一" in str(ei.value)


def test_validate_fuzzy_whitespace_match(tmp_path):
    _write(tmp_path, "a.py", "def  f():\n    return 1\n")
    patch = file_patch("a.py", "def f():\n    return 1\n",
                       "def f():\n    return 2\n")
    out = validate_patch(str(tmp_path), patch)
    assert out["files"][0]["hunks"][0]["new"].endswith("return 2\n")


def test_validate_create_requires_absent_file(tmp_path):
    _write(tmp_path, "a.txt", "x")
    patch = {"files": [{"op": "create", "path": "a.txt", "content": "y"}]}
    with pytest.raises(PatchError):
        validate_patch(str(tmp_path), patch)


def test_validate_write_requires_allow_create(tmp_path):
    patch = {"files": [{"op": "write", "path": "new.txt", "content": "y"}]}
    with pytest.raises(PatchError):
        validate_patch(str(tmp_path), patch)
    patch["files"][0]["allow_create"] = True
    assert validate_patch(str(tmp_path), patch)["files"][0]["op"] == "write"


def test_validate_checks_base_hash(tmp_path):
    p = _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "print(1)", "print(2)")
    patch["files"][0]["base_hash"] = sha256_file(p)
    assert validate_patch(str(tmp_path), patch)
    _write(tmp_path, "a.py", "print(9)\n")
    with pytest.raises(PatchError) as ei:
        validate_patch(str(tmp_path), patch)
    assert "base_hash" in str(ei.value)


def test_validate_simulates_create_then_update_in_one_patch(tmp_path):
    patch = {"files": [
        {"op": "create", "path": "new.py", "content": "v = 1\n"},
        {"op": "update", "path": "new.py",
         "hunks": [{"old": "v = 1", "new": "v = 2"}]},
    ]}
    out = validate_patch(str(tmp_path), patch)
    assert [f["op"] for f in out["files"]] == ["create", "update"]


def test_dry_run_reports_changed_without_writing(tmp_path):
    _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "print(1)", "print(2)")
    r = dry_run_patch(str(tmp_path), patch)
    assert r["ok"] is True
    assert r["files"][0]["changed"] is True
    assert _read(tmp_path, "a.py") == "print(1)\n"


def test_dry_run_detects_python_syntax_error(tmp_path):
    _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "print(1)", "print(")
    r = dry_run_patch(str(tmp_path), patch)
    assert r["ok"] is False
    assert "语法错误" in r["errors"][0]


def test_dry_run_blocks_whole_batch(tmp_path):
    _write(tmp_path, "ok.py", "a = 1\n")
    patch = {"files": [
        {"op": "update", "path": "ok.py",
         "hunks": [{"old": "a = 1", "new": "a = 2"}]},
        {"op": "create", "path": "bad.py", "content": "def f(:\n"},
    ]}
    with pytest.raises(PatchError):
        apply_patch(str(tmp_path), patch)
    assert _read(tmp_path, "ok.py") == "a = 1\n"
    assert not os.path.exists(os.path.join(str(tmp_path), "bad.py"))


def test_apply_update_then_rollback(tmp_path):
    _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "print(1)", "print(2)", reason="演示")
    r = apply_patch(str(tmp_path), patch)
    assert r["ok"] is True and r["applied"] == ["a.py"]
    assert _read(tmp_path, "a.py") == "print(2)\n"
    assert os.path.isfile(r["backup_manifest"])
    back = rollback(r["backup_manifest"])
    assert back["ok"] is True and back["restored"] == ["a.py"]
    assert _read(tmp_path, "a.py") == "print(1)\n"


def test_apply_create_delete_rename(tmp_path):
    _write(tmp_path, "old.txt", "old")
    _write(tmp_path, "move.txt", "moving")
    patch = {"files": [
        {"op": "create", "path": "new.txt", "content": "new"},
        {"op": "delete", "path": "old.txt"},
        {"op": "rename", "path": "move.txt", "new_path": "moved.txt"},
    ]}
    r = apply_patch(str(tmp_path), patch)
    assert r["ok"] is True
    assert _read(tmp_path, "new.txt") == "new"
    assert not os.path.exists(os.path.join(str(tmp_path), "old.txt"))
    assert not os.path.exists(os.path.join(str(tmp_path), "move.txt"))
    assert _read(tmp_path, "moved.txt") == "moving"
    manifest = json.loads(open(r["backup_manifest"], encoding="utf-8").read())
    assert {f["op"] for f in manifest["files"]} == {"create", "delete", "rename"}


def test_apply_selected_hunks_only(tmp_path):
    _write(tmp_path, "a.py", "one\ntwo\n")
    patch = {"files": [{"op": "update", "path": "a.py", "hunks": [
        {"old": "one", "new": "ONE"},
        {"old": "two", "new": "TWO"},
    ]}]}
    apply_patch(str(tmp_path), patch, selected_hunks={"a.py:0"})
    assert _read(tmp_path, "a.py") == "ONE\ntwo\n"


def test_unified_diff_contains_change(tmp_path):
    _write(tmp_path, "a.py", "print(1)\n")
    patch = file_patch("a.py", "print(1)", "print(2)")
    diff = unified_diff(str(tmp_path), patch)
    assert "-print(1)" in diff and "+print(2)" in diff


def test_rollback_rejects_unreadable_manifest(tmp_path):
    with pytest.raises(PatchError):
        rollback(str(tmp_path / "nope.json"))


# ---------------- 批次 O3：多文件重构按文件分组应用 ----------------
def _two_file_patch():
    return {"goal": "跨文件重构", "files": [
        {"op": "update", "path": "a.py",
         "hunks": [{"old": "x = 1", "new": "x = 2"}]},
        {"op": "create", "path": "b.py", "content": "def helper():\n    return 1\n"},
    ]}


def test_group_by_file_keeps_order_and_filters(tmp_path):
    from core.patch_engine import group_by_file

    patch = _two_file_patch()
    assert [rel for rel, _ in group_by_file(patch)] == ["a.py", "b.py"]
    only = group_by_file(patch, selected_files=["b.py"])
    assert [rel for rel, _ in only] == ["b.py"]
    assert only[0][1]["files"][0]["path"] == "b.py"


def test_grouped_apply_writes_every_file_once(tmp_path):
    from core.patch_engine import apply_patch_grouped

    _write(tmp_path, "a.py", "x = 1\n")
    r = apply_patch_grouped(str(tmp_path), _two_file_patch())
    assert r["ok"] is True, r
    assert r["applied"] == ["a.py", "b.py"]
    assert [f["ok"] for f in r["files"]] == [True, True]
    assert r["manifests"] and os.path.isfile(r["backup_manifest"])
    back = rollback(r["backup_manifest"])
    assert back["ok"] is True
    assert _read(tmp_path, "a.py") == "x = 1\n"
    assert not os.path.exists(os.path.join(str(tmp_path), "b.py"))


def test_grouped_apply_rolls_back_only_failed_file(tmp_path, monkeypatch):
    """第二个文件落盘失败时只回滚它自己这一组，第一个文件保留。"""
    import core.patch_engine as pe

    _write(tmp_path, "a.py", "x = 1\n")
    real = pe.apply_patch
    calls = {"n": 0}

    def flaky(root, patch, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PatchError("第二个文件写入失败")
        return real(root, patch, **kwargs)

    monkeypatch.setattr(pe, "apply_patch", flaky)
    r = pe.apply_patch_grouped(str(tmp_path), _two_file_patch())
    assert r["ok"] is False
    assert any("b.py" in e for e in r["errors"])
    assert [f["ok"] for f in r["files"]] == [True, False]
    assert _read(tmp_path, "a.py") == "x = 2\n", "第一个文件不该被回滚"
    assert not os.path.exists(os.path.join(str(tmp_path), "b.py"))
    # 合并清单仍能把已落盘的部分撤销。
    rollback(r["backup_manifest"])
    assert _read(tmp_path, "a.py") == "x = 1\n"


def test_grouped_apply_blocks_whole_batch_before_write(tmp_path):
    from core.patch_engine import apply_patch_grouped

    _write(tmp_path, "a.py", "x = 1\n")
    patch = {"files": [
        {"op": "update", "path": "a.py",
         "hunks": [{"old": "x = 1", "new": "x = 2"}]},
        {"op": "create", "path": "bad.py", "content": "def f(:\n"},
    ]}
    with pytest.raises(PatchError):
        apply_patch_grouped(str(tmp_path), patch)
    assert _read(tmp_path, "a.py") == "x = 1\n"
    assert not os.path.exists(os.path.join(str(tmp_path), "bad.py"))
