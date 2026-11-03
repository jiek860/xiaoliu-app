# -*- coding: utf-8 -*-
"""第 8 批 B5 + 深度⑧⑨⑩：诊断三源合并、波浪线、问题页标色与「让 AI 修这一行」。"""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtGui import QTextCursor  # noqa: E402
from PyQt5.QtWidgets import QApplication, QPlainTextEdit  # noqa: E402

from gui import editor_lint as el  # noqa: E402
from gui import ide_editor_shell as shell  # noqa: E402
from gui.code_editor_ai import (CodeEditorAIMixin, keep_indent,  # noqa: E402
                                replace_line_text)
from gui.code_editor_widget import CodeEditWidget  # noqa: E402
from gui.ide_editor_shell import BottomPanel  # noqa: E402
from gui.workbench_problems import SEVERITY_COLORS, row_severity  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeClient:
    """只提供编辑器用到的那两个方法。"""

    def __init__(self, items):
        self._items = list(items)
        self.changed = []

    def diagnostics_for(self, path):
        return list(self._items)

    def did_change(self, text, path=None):
        self.changed.append(text)
        return None


class _FakeTrunk:
    def __init__(self, rules=None, modules=None, base=""):
        self._rules = dict(rules or {})
        self.modules = dict(modules or {})
        self.base = base

    def rule(self, name, default=None):
        return self._rules.get(name, default)


def _widget(app, tmp_path, text, name="a.py"):
    path = str(tmp_path / name)
    w = CodeEditWidget()
    w.trunk = _FakeTrunk()
    w.setPlainText(text)
    w.filepath = path
    return w


# ---------------------------------------------------------------- 三源合并
def test_lint_rows_prefers_lsp_diagnostics(app, tmp_path):
    w = _widget(app, tmp_path, "x = 1\n")
    client = _FakeClient([{"severity": 1, "message": "类型不匹配",
                           "range": {"start": {"line": 0, "character": 1}}}])
    w._lsp_client = lambda autostart=True: client
    try:
        rows = w._apply_problems(w.lint_rows())
        assert rows == [(1, 2, "LSP·LSP", "类型不匹配")]
        assert client.changed, "编辑后应把文本推给语言服务（did_change）"
        assert len(w.extraSelections()) == 1
    finally:
        w.close()
        w.deleteLater()


def test_lint_rows_falls_back_to_ast(app, tmp_path):
    w = _widget(app, tmp_path, "def broken(:\n")
    w._lsp_client = lambda autostart=True: None
    try:
        rows = w.lint_rows()
        assert rows and rows[0][2] == "SyntaxError"
    finally:
        w.close()
        w.deleteLater()


def test_lint_rows_ignores_non_python_files(app, tmp_path):
    w = _widget(app, tmp_path, "let x = 1;\n", name="app.js")
    try:
        assert w.lint_rows() == []
        w._apply_problems([])
        assert w.extraSelections() == []
    finally:
        w.close()
        w.deleteLater()


def test_live_lint_marks_every_problem(app, tmp_path, monkeypatch):
    w = _widget(app, tmp_path, "import os\nx = 1\n")
    rows = [(1, 1, "F401", "`os` imported but unused"),
            (2, 1, "E225", "missing whitespace")]
    monkeypatch.setattr(el.code_lint, "live_ruff", lambda *a, **k: list(rows))
    seen = []
    w.problemsChanged.connect(seen.append)
    try:
        got = w._lint_live()
        assert got == rows
        assert seen[-1] == rows
        assert w.problems() == rows
        # 深度⑨：所有问题行都画波浪线，不只第一条
        assert len(w.extraSelections()) == 2
    finally:
        w.close()
        w.deleteLater()


def test_live_lint_respects_switch(app, tmp_path, monkeypatch):
    w = _widget(app, tmp_path, "import os\n")
    w.trunk = _FakeTrunk({"编辑.实时检查": False})
    w._live_timer.stop()          # 清掉 setPlainText 排的那一次
    calls = []
    monkeypatch.setattr(el.code_lint, "live_ruff",
                        lambda *a, **k: calls.append(a) or [])
    try:
        w._lint_schedule()
        assert not w._live_timer.isActive(), "关掉实时检查后不该再排期"
        w.lint_rows(live=True)
        assert calls == []
    finally:
        w.close()
        w.deleteLater()


def test_underline_clears_when_no_rows(app):
    w = CodeEditWidget()
    try:
        w.setPlainText("a = 1\nb = 2\nc = 3\n")
        w.underline_problems([(1, 1, "E1", ""), (3, 2, "E2", "")])
        assert len(w.extraSelections()) == 2
        assert w.underline_problems([]) == []
        assert w.extraSelections() == []
        # 行号越界不该抛异常
        w.underline_problems([(999, 1, "E1", ""), ("bad", 0, "x", "")])
    finally:
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------- 问题页
def test_row_severity_maps_codes():
    assert row_severity("F401") == "error"
    assert row_severity("SyntaxError") == "error"
    assert row_severity("运行") == "error"
    assert row_severity("W291") == "warn"
    assert row_severity("LSP·pyright", "类型错误") == "error"
    assert row_severity("LSP·ruff", "⚠ 未使用") == "warn"


def test_problem_page_colors_by_severity(app):
    box = BottomPanel(QPlainTextEdit())
    try:
        box.set_problems([(2, 1, "F401", "unused"), (5, 1, "W291", "空格")])
        err = box.problems.item(0).foreground().color().name()
        warn = box.problems.item(1).foreground().color().name()
        assert err == SEVERITY_COLORS["error"]
        assert warn == SEVERITY_COLORS["warn"]
    finally:
        box.close()
        box.deleteLater()


def test_problem_page_right_click_offers_fix(app, monkeypatch):
    class _FakeAction:
        def __init__(self, text):
            self._text = text
            self.triggered = []

        def text(self):
            return self._text

    class _FakeMenu:
        def __init__(self, parent=None):
            self._acts = []

        def addAction(self, text):
            act = _FakeAction(text)
            self._acts.append(act)
            return act

        def exec_(self, *_a):
            return self._acts[0]          # 永远点第一个 = 让 AI 修这一行

    monkeypatch.setattr(shell, "QMenu", _FakeMenu)
    box = BottomPanel(QPlainTextEdit())
    fired, jumped = [], []
    box.fixRequested.connect(fired.append)
    box.jumpRequested.connect(jumped.append)
    try:
        box.set_problems([(2, 1, "F401", "unused")])
        assert box._problem_actions(box.problems.item(0)) == "fix"
        assert fired == [2]
        assert jumped == []
    finally:
        box.close()
        box.deleteLater()


# ---------------------------------------------------------------- 一键修一行
def test_widget_fix_request_falls_back_to_chat(app):
    w = CodeEditWidget()
    sent = []
    w.askAssistantRequested.connect(sent.append)
    try:
        w._apply_problems([(2, 1, "F401", "`os` imported but unused")])
        w.setPlainText("import os\nx = 1\n")
        w._apply_problems([(2, 1, "F401", "`os` imported but unused")])
        assert w.problem_on_line(2) == (2, 1, "F401", "`os` imported but unused")
        assert w.problem_on_line(7) is None
        assert w.fix_line_request(2) is True
        assert sent and "第 2 行" in sent[-1] and "F401" in sent[-1]
        assert w.fix_line_request(7) is False       # 本行没问题：只提示，不发请求
    finally:
        w.close()
        w.deleteLater()


def test_fix_prompt_carries_line_and_reason(app):
    w = CodeEditWidget()
    try:
        w.setPlainText("a = 1\nprint(b)\n")
        w._apply_problems([(2, 1, "F821", "undefined name 'b'")])
        prompt = w.fix_prompt(2, w.problem_on_line(2))
        assert "第 2 行" in prompt and "print(b)" in prompt
        assert "undefined name" in prompt
    finally:
        w.close()
        w.deleteLater()


def test_fix_menu_item_present(app, monkeypatch):
    w = CodeEditWidget()
    try:
        menu = type("M", (), {})
        added = []

        class _Menu:
            def addAction(self, text):
                act = types.SimpleNamespace(text=text, triggered=[])
                added.append(act)
                return act

        w._apply_problems([(1, 1, "E1", "错误")])
        w._fix_add_menu(_Menu())
        assert len(added) == 1
        assert "让 AI 修这一行" in added[0].text
        # 关掉开关就没有这个入口
        w.trunk = _FakeTrunk({"编辑.一键修复": False})
        before = len(added)
        w._fix_add_menu(_Menu())
        assert len(added) == before
    finally:
        w.close()
        w.deleteLater()


class _LLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, _msgs):
        return self.reply


class _FixHost(CodeEditorAIMixin):
    def __init__(self, reply, base):
        self.trunk = _FakeTrunk(modules={"llm": _LLM(reply)}, base=str(base))
        self.output = QPlainTextEdit()

    def _preview_ai_change(self, w, old, new, apply=None, title=""):
        if callable(apply):
            apply()
        return True


def test_replace_line_text_keeps_other_lines():
    code = "a = 1\nb = 2\nc = 3\n"
    assert replace_line_text(code, 2, "b = 20") == "a = 1\nb = 20\nc = 3\n"
    assert replace_line_text(code, 9, "z") == code
    assert replace_line_text(code, "bad", "z") == code


def test_keep_indent_reuses_old_prefix():
    assert keep_indent("    x = 1", "x = 2") == "    x = 2"
    assert keep_indent("    x = 1", "    x = 2") == "    x = 2"
    assert keep_indent("x = 1", "y = 2") == "y = 2"
    assert keep_indent("    x = 1", "") == ""


def test_fix_line_with_ai_changes_only_that_line(app, tmp_path):
    w = CodeEditorWidgetForTest()
    try:
        w.setPlainText("def f():\n    return Non\n\nprint(f())\n")
        host = _FixHost('{"new": "    return None", "reason": "拼写"}', tmp_path)
        ok = host.fix_line_with_ai(w, 2, (2, 5, "F821", "undefined name 'Non'"))
        assert ok is True
        assert w.toPlainText().splitlines()[1] == "    return None"
        assert w.toPlainText().splitlines()[0] == "def f():"
        assert w.toPlainText().splitlines()[3] == "print(f())"
    finally:
        w.close()
        w.deleteLater()


def test_fix_line_with_ai_without_llm_returns_false(app, tmp_path):
    w = CodeEditorWidgetForTest()
    try:
        w.setPlainText("a = 1\nb = 2\n")
        host = _FixHost("", tmp_path)
        host.trunk.modules = {}
        assert host.fix_line_with_ai(w, 2, None) is False
        assert w.toPlainText() == "a = 1\nb = 2\n"
    finally:
        w.close()
        w.deleteLater()


def test_fix_line_with_ai_jumps_out_of_range(app, tmp_path):
    w = CodeEditorWidgetForTest()
    try:
        w.setPlainText("a = 1\n")
        host = _FixHost('{"new": "b = 2"}', tmp_path)
        assert host.fix_line_with_ai(w, 99, None) is False
    finally:
        w.close()
        w.deleteLater()


def CodeEditorWidgetForTest():
    """独立控件（不挂宿主窗口）：修一行只用到 document/QTextCursor。"""
    w = CodeEditWidget()
    w.trunk = _FakeTrunk()
    return w


def test_move_cursor_keeps_problem_lookup_consistent(app):
    w = CodeEditWidget()
    try:
        w.setPlainText("a = 1\nb = 2\n")
        w._apply_problems([(2, 1, "E1", "错误")])
        cur = QTextCursor(w.document().findBlockByNumber(1))
        w.setTextCursor(cur)
        assert w.problem_at_cursor() == (2, 1, "E1", "错误")
    finally:
        w.close()
        w.deleteLater()
