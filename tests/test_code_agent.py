# -*- coding: utf-8 -*-
"""代码工作区索引与多文件 patch 引擎测试。"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402
_app = QApplication.instance() or QApplication([])

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.workspace_index import WorkspaceIndex  # noqa: E402
from core.patch_engine import (  # noqa: E402
    PatchError, apply_patch, file_patch, rollback, unified_diff,
    validate_patch,
)


def test_workspace_index_symbols_tests_search(tmp_path):
    root = tmp_path / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "a.py").write_text(
        "import os\n\nclass Foo:\n    def method(self):\n        pass\n\n"
        "def bar():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_a.py").write_text(
        "from pkg import a\n\ndef test_bar():\n    assert a.bar() == 1\n",
        encoding="utf-8")
    idx = WorkspaceIndex(str(tmp_path / "index_base"), str(root))
    stats = idx.rebuild()
    assert stats["files"] >= 2
    assert idx.find_symbols("Foo")
    assert idx.find_symbols("bar")
    assert "os" in idx.imports_of("pkg/a.py")
    assert "tests/test_a.py" in idx.related_tests("pkg/a.py")
    hits = idx.search_text("return 1")
    assert any(h["file"].endswith("a.py") for h in hits)
    info = idx.stats()
    assert info["symbols"] >= 3


def test_patch_apply_and_rollback(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("hello\nold value\nend\n", encoding="utf-8")
    patch = file_patch("a.txt", "old value", "new value", "测试")
    v = validate_patch(str(root), patch)
    diff = unified_diff(str(root), v)
    assert "-old value" in diff and "+new value" in diff
    r = apply_patch(str(root), patch)
    assert r["ok"] is True
    assert "new value" in (root / "a.txt").read_text(encoding="utf-8")
    rb = rollback(r["backup_manifest"])
    assert rb["ok"] is True
    assert "old value" in (root / "a.txt").read_text(encoding="utf-8")


def test_patch_rejects_non_unique_old_text(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("same\nsame\n", encoding="utf-8")
    patch = file_patch("a.txt", "same", "other")
    with pytest.raises(PatchError):
        validate_patch(str(root), patch)


def test_patch_rejects_wrong_base_hash(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    patch = file_patch("a.txt", "old", "new")
    patch["files"][0]["base_hash"] = "deadbeef"
    with pytest.raises(PatchError):
        validate_patch(str(root), patch)


def test_diff_review_dialog_applies_selected_patch(tmp_path):
    from gui.diff_dialog import DiffReviewDialog
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    patch = file_patch("a.txt", "old", "new", "对话框应用测试")
    d = DiffReviewDialog(str(root), patch)
    try:
        assert d.tree.topLevelItemCount() == 1
        d._apply()
        assert d.accepted is True
        assert (root / "a.txt").read_text(encoding="utf-8") == "new\n"
    finally:
        d.close()


def test_trunk_exposes_workspace_index():
    from tests.conftest import make_trunk
    trunk = make_trunk()
    idx = trunk.get_workspace_index()
    assert idx.root == os.path.abspath(trunk.base)
    assert idx is trunk.get_workspace_index()


def test_code_agent_dialog_constructs(tmp_path):
    from tests.conftest import make_trunk
    from gui.code_agent_dialog import CodeAgentDialog
    trunk = make_trunk()
    d = CodeAgentDialog(trunk, root=str(tmp_path))
    try:
        assert d.windowTitle() == "代码 Agent"
        assert d.goal.placeholderText()
    finally:
        d.close()
