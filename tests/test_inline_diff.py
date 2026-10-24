# -*- coding: utf-8 -*-
"""内联 diff 预览：行号映射、跳转信号、应用/撤销。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

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
