# -*- coding: utf-8 -*-
"""批次 47.3：代码问答五模板（解释/定位/影响面/用法/对比）。

用真实的 WorkspaceIndex（临时目录）验证引用准确性：回答里必须带
`文件:行`，且 refs 指向定义所在行。
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import agent_router as ar  # noqa: E402
from gui.ai_dock_service import AgentDockServiceMixin  # noqa: E402


class FakeTrunk:
    def __init__(self, rules=None):
        self.rules = dict(rules or {})

    def rule(self, key, default=None):
        return self.rules.get(key, default)


@pytest.fixture()
def workspace(tmp_path):
    """小工作区：mod.py 两个函数 + 一个引用它的测试文件。"""
    (tmp_path / "mod.py").write_text(
        "def helper(value):\n"
        '    """把值转成字符串。"""\n'
        "    return str(value)\n"
        "\n"
        "\n"
        "def other(value):\n"
        "    return value * 2\n",
        encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from mod import helper\n\n\n"
        "def test_helper():\n"
        "    assert helper(1) == '1'\n",
        encoding="utf-8")
    from core.workspace_index import WorkspaceIndex
    idx = WorkspaceIndex(str(tmp_path), str(tmp_path))
    idx.refresh()
    return tmp_path, idx


# ---------------------------------------------------------------- 分类
def test_classify_five_templates():
    assert ar.classify_code_question("解释一下 helper")["template"] == "explain"
    assert ar.classify_code_question("helper 在哪")["template"] == "locate"
    assert ar.classify_code_question("helper 会影响哪些地方")["template"] \
        == "impact"
    assert ar.classify_code_question("helper 怎么用")["template"] == "usage"
    info = ar.classify_code_question("helper 和 other 有什么区别")
    assert info["template"] == "compare"
    assert info["targets"] == ["helper", "other"]


def test_classify_compare_with_one_target_becomes_explain():
    info = ar.classify_code_question("helper 的区别是什么")
    assert info["template"] == "explain"


def test_classify_rejects_actions_and_plain_chat():
    assert ar.classify_code_question("帮我改一下 helper") is None
    assert ar.classify_code_question("修复 helper 的报错") is None
    assert ar.classify_code_question("你好") is None
    assert ar.classify_code_question("解释一下") is None


def test_classify_extracts_quoted_and_file_targets():
    info = ar.classify_code_question("解释 `core/x.py` 里做了什么")
    assert "core/x.py" in info["targets"]


# ---------------------------------------------------------------- 开关
def test_switch_default_off():
    assert ar.code_qa_enabled(None) is False
    assert ar.code_qa_enabled(FakeTrunk()) is False
    assert ar.code_qa_enabled(FakeTrunk({"code_qa.enabled": True})) is True
    assert ar.code_qa_enabled(FakeTrunk({"code_qa.enabled": "on"})) is True
    assert ar.code_qa_enabled(FakeTrunk({"code_qa.enabled": "0"})) is False


# ---------------------------------------------------------------- 回答
def test_locate_answer_has_path_and_line(workspace):
    root, idx = workspace
    r = ar.answer_code_question("helper 在哪", root=str(root), index=idx)
    assert r["ok"] is True
    assert r["template"] == "locate"
    assert any(ref["path"] == "mod.py" for ref in r["refs"])
    assert "mod.py:%d" % r["refs"][0]["line"] in r["answer"]
    assert r["refs"][0]["line"] == 1


def test_explain_answer_includes_signature(workspace):
    root, idx = workspace
    r = ar.answer_code_question("解释一下 helper", root=str(root), index=idx)
    assert r["ok"] is True
    assert "def helper(value):" in r["answer"]


def test_usage_answer_lists_related_tests(workspace):
    root, idx = workspace
    r = ar.answer_code_question("helper 怎么用", root=str(root), index=idx)
    assert r["ok"] is True
    assert "test_mod.py" in r["answer"]


def test_impact_answer_mentions_tests(workspace):
    root, idx = workspace
    r = ar.answer_code_question("helper 会影响哪些地方", root=str(root), index=idx)
    assert r["ok"] is True
    assert "相关测试" in r["answer"]


def test_compare_answer_covers_two_symbols(workspace):
    root, idx = workspace
    r = ar.answer_code_question("helper 和 other 有什么区别",
                               root=str(root), index=idx)
    assert r["ok"] is True
    assert r["template"] == "compare"
    names = {ref["symbol"] for ref in r["refs"]}
    assert {"helper", "other"} <= names
    assert "差异" in r["answer"]


def test_file_question_resolves_to_file_reference(workspace):
    root, idx = workspace
    r = ar.answer_code_question("解释一下 mod.py", root=str(root), index=idx)
    assert r["ok"] is True
    assert r["refs"][0] == {"path": "mod.py", "line": 1,
                            "symbol": "mod.py", "kind": "file"}


def test_unknown_symbol_returns_not_ok(workspace):
    root, idx = workspace
    r = ar.answer_code_question("解释一下 zzz_missing_symbol",
                               root=str(root), index=idx)
    assert r["ok"] is False
    assert r["reason"]


def test_every_ref_has_file_and_line(workspace):
    root, idx = workspace
    r = ar.answer_code_question("解释 helper", root=str(root), index=idx)
    for ref in r["refs"]:
        assert ref["path"] and int(ref["line"]) >= 1
        assert "%s:%d" % (ref["path"], ref["line"]) in r["answer"]


# ---------------------------------------------------------------- 面板接线
class _Timeline:
    def __init__(self):
        self.lines = []

    def clear(self):
        self.lines.clear()

    def appendPlainText(self, text):
        self.lines.append(str(text))

    def text(self):
        return "\n".join(self.lines)


class _Dock(AgentDockServiceMixin):
    def __init__(self, wb):
        self.wb = wb
        self.timeline = _Timeline()


class _Editor:
    def __init__(self):
        self.opened = []

    def open_path_at(self, path, line=1):
        self.opened.append((path, line))


class _WB:
    def __init__(self, trunk, root=".", editor=None):
        self.trunk = trunk
        self.root = root
        self._editor = editor


def test_dock_answers_question_when_switch_on(workspace):
    root, idx = workspace
    dock = _Dock(_WB(FakeTrunk({"code_qa.enabled": True}), root=str(root)))
    assert dock.try_code_qa("helper 在哪") is True
    text = dock.timeline.text()
    assert "mod.py" in text and ":" in text
    assert "可跳转" in text


def test_dock_ignores_question_when_switch_off(workspace):
    root, idx = workspace
    dock = _Dock(_WB(FakeTrunk(), root=str(root)))
    assert dock.try_code_qa("helper 在哪") is False
    assert dock.timeline.text() == ""


def test_dock_falls_back_when_symbol_missing(workspace):
    root, idx = workspace
    dock = _Dock(_WB(FakeTrunk({"code_qa.enabled": True}), root=str(root)))
    assert dock.try_code_qa("解释 zzz_missing") is False


def test_open_reference_jumps_in_editor(workspace):
    root, idx = workspace
    editor = _Editor()
    dock = _Dock(_WB(FakeTrunk(), root=str(root), editor=editor))
    dock.open_reference("mod.py", 3)
    assert editor.opened == [("mod.py", 3)]


def test_link_text_view_emits_ref_on_click():
    pytest.importorskip("PyQt5.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication
    from gui.ai_dock_service import LinkPlainTextEdit

    app = QApplication.instance() or QApplication([])  # noqa: F841
    view = LinkPlainTextEdit()
    got = []
    view.refClicked.connect(lambda p, l: got.append((p, l)))
    try:
        view.setPlainText("- `mod.py:3` 定义\n- 没有引用的普通文字")
        block = view.document().firstBlock()
        cursor = view.textCursor()
        cursor.setPosition(block.position() + 4)     # "mod.py:3" 中间
        rect = view.cursorRect(cursor)
        assert view._emit_ref(QPoint(rect.center().x(), rect.center().y()))
        assert got == [("mod.py", 3)]
        got.clear()
        last = view.document().lastBlock()
        cursor.setPosition(last.position() + 2)
        rect = view.cursorRect(cursor)
        assert view._emit_ref(QPoint(rect.center().x(), rect.center().y())) \
            is False
        assert got == []
    finally:
        view.deleteLater()
