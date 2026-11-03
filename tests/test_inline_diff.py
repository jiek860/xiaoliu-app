# -*- coding: utf-8 -*-
"""内联 diff 预览：行号映射、跳转信号、应用/撤销。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtCore import QUrl  # noqa: E402
from PyQt5.QtGui import QTextCursor  # noqa: E402

from gui.inline_diff import InlineDiffView  # noqa: E402


def _patch():
    return {"goal": "改 a", "files": [
        {"path": "a.py", "hunks": [{"old": "x = 1", "new": "x = 2"}]}]}


def test_diff_targets_and_apply_undo(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\ny = 3\n", encoding="utf-8")
    view = InlineDiffView(str(root), _patch())
    qtbot.addWidget(view)
    targets = view._targets
    assert targets
    assert any(rel == "a.py" and line >= 1 for rel, line in targets.values())
    view._apply()
    assert "x = 2" in (root / "a.py").read_text(encoding="utf-8")
    assert view._applied is True
    view._undo()
    assert (root / "a.py").read_text(encoding="utf-8") == "x = 1\ny = 3\n"
    assert view._applied is False


def test_jump_signal_on_cursor_move(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    view = InlineDiffView(str(root), _patch())
    qtbot.addWidget(view)
    got = []
    view.jumpRequested.connect(lambda rel, line: got.append((rel, line)))
    pos = sorted(view._targets)[0]
    block = view.diff.document().findBlockByNumber(pos)
    view.diff.setTextCursor(QTextCursor(block))
    if not got:  # 光标已在原地时手动触发一次
        view._on_cursor()
    assert got and got[0][0] == "a.py"


def test_mark_applied_does_not_write(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    view = InlineDiffView(str(root), _patch())
    view.mark_applied("manifest.json")
    assert view._applied is True
    assert view.manifest == "manifest.json"
    assert (root / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def _two_hunk_patch():
    return {"goal": "改两段", "files": [{"path": "a.py", "hunks": [
        {"old": "x = 1\n", "new": "x = 10\n"},
        {"old": "y = 2\n", "new": "y = 20\n"}]}]}


def test_hunk_panel_lists_rows_and_applies_one(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    view = InlineDiffView(str(root), _two_hunk_patch())
    qtbot.addWidget(view)
    assert len(view._plan["hunks"]) == 2
    assert "精确定位" in view.hunk_panel.toHtml()
    view._on_anchor(QUrl("applyhunk://a.py:0"))
    text = (root / "a.py").read_text(encoding="utf-8")
    assert "x = 10" in text and "y = 2" in text
    assert "a.py:0" in view._applied_keys
    view._on_anchor(QUrl("undohunk://a.py:0"))
    assert (root / "a.py").read_text(encoding="utf-8") == "x = 1\ny = 2\n"


def test_skip_hunk_then_apply_all(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    view = InlineDiffView(str(root), _two_hunk_patch())
    qtbot.addWidget(view)
    view._on_anchor(QUrl("skiphunk://a.py:0"))
    assert "a.py:0" in view._skipped
    view._apply()
    text = (root / "a.py").read_text(encoding="utf-8")
    assert "x = 1" in text and "y = 20" in text


def test_conflict_links_and_keep_mine(tmp_path, qtbot):
    root = tmp_path / "p"
    root.mkdir()
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    view = InlineDiffView(str(root), _patch())
    qtbot.addWidget(view)
    (root / "a.py").write_text("x = 5\n", encoding="utf-8")
    view._refresh_hunks()
    assert "a.py:0" in view._conflicts
    assert "保留我的" in view.hunk_panel.toHtml()
    view._on_anchor(QUrl("minehunk://a.py:0"))
    assert "a.py:0" in view._skipped
    view._apply()
    assert (root / "a.py").read_text(encoding="utf-8") == "x = 5\n"
