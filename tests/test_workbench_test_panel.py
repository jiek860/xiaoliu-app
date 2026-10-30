# -*- coding: utf-8 -*-
"""工作台「测试」页：选测参数、失败定位与跳转接线。"""

import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5.QtWidgets")
pytest.importorskip("PyQt5.QtCore")
from PyQt5.QtWidgets import QApplication, QPlainTextEdit  # noqa: E402

from gui.workbench_test_panel import (  # noqa: E402
    TestPanel, changed_paths, failure_text, pytest_args, summarize,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeWidget:
    def __init__(self, filepath=""):
        self.filepath = filepath


class _FakeTabs:
    def __init__(self, widgets):
        self._widgets = widgets

    def count(self):
        return len(self._widgets)

    def widget(self, i):
        return self._widgets[i]


class _FakeIndex:
    def __init__(self, mapping):
        self.mapping = mapping

    def related_tests(self, rel):
        return self.mapping.get(rel, [])


class _FakeTrunk:
    def __init__(self, index):
        self.index = index

    def get_workspace_index(self):
        return self.index


class _FakeDialog:
    root = BASE

    def __init__(self, widgets=(), index=None):
        self.tabs = _FakeTabs(list(widgets))
        self.trunk = _FakeTrunk(index or _FakeIndex({}))
        self.opened = []

    def open_path_at(self, path, line=1):
        self.opened.append((path, line))


# ---------------------------------------------------------------- 纯函数
def test_changed_paths_only_open_py():
    d = _FakeDialog([_FakeWidget(os.path.join(BASE, "core/trunk.py")),
                     _FakeWidget(""), _FakeWidget("README.md")])
    assert changed_paths(d) == ["core/trunk.py"]


def test_pytest_args_modes():
    assert pytest_args() == ["-m", "pytest", "-q"]
    assert pytest_args(["tests/test_a.py"]) == [
        "-m", "pytest", "-q", "tests/test_a.py"]
    assert pytest_args(failed=["tests/test_a.py::test_x"]) == [
        "-m", "pytest", "-q", "-x", "tests/test_a.py::test_x"]


def test_failure_and_summary_text():
    assert failure_text({"file": "core/trunk.py", "line": 42,
                         "symbol": "call"}) == "core/trunk.py:42  (call)"
    assert failure_text({}) == "?:0"
    assert summarize(0, [], []) == "测试通过"
    assert summarize(5, [], []) == "没有收集到测试"
    assert summarize(1, ["a::b"], [{"file": "x", "line": 1}]) == \
        "失败 1 个用例，定位 1 处"


def test_select_related_uses_index(app):
    d = _FakeDialog([_FakeWidget(os.path.join(BASE, "core/trunk.py"))],
                    _FakeIndex({"core/trunk.py": ["tests/test_trunk.py"]}))
    panel = TestPanel(d)
    tests = panel.select_related()
    assert tests == ["tests/test_trunk.py"]
    assert panel.list.count() == 1
    assert "受影响测试 1 个" in panel.title.text()


def test_select_related_empty(app):
    panel = TestPanel(_FakeDialog())
    assert panel.select_related() == []
    assert "没有找到受影响测试" in panel.title.text()


# ---------------------------------------------------------------- 面板
def test_done_parses_failures_and_jump(app):
    panel = TestPanel(_FakeDialog())
    d = _FakeDialog()
    panel.jumpTo.connect(d.open_path_at)
    panel._started = time.monotonic()
    panel._buffer = (
        "F\nFAILED tests/test_a.py::test_x - assert 1\n"
        'File "core/trunk.py", line 12, in call\n1 failed\n')
    panel._done(1, 0)
    assert panel.failed == ["tests/test_a.py::test_x"]
    assert panel.found and panel.found[0]["file"] == "core/trunk.py"
    assert "失败 1 个用例" in panel.title.text()
    assert panel.list.count() == 2      # 1 个定位 + 1 个失败用例
    item = panel.list.item(0)
    panel._activate(item)
    assert d.opened and d.opened[0][0] == "core/trunk.py"


def test_rerun_failed_without_failures(app):
    panel = TestPanel(_FakeDialog())
    assert panel.rerun_failed() is False
    assert "还没有失败用例" in panel.title.text()


def test_run_is_not_reentrant(app):
    panel = TestPanel(_FakeDialog())

    class _Running:
        def state(self):
            return 4  # QProcess.Running

    panel.proc = _Running()
    assert panel.run(["tests/test_a.py"]) is False
    assert "测试正在跑" in panel.title.text()


def test_panel_clear(app):
    panel = TestPanel(_FakeDialog())
    panel._buffer = "noise"
    panel.output.setPlainText("noise")
    panel.clear()
    assert panel.failed == [] and panel.output.toPlainText() == ""
    assert "尚未运行" in panel.title.text()


def test_attach_adds_bottom_tab(app):
    from gui.ide_editor_shell import BottomPanel
    from gui.workbench_test_panel import attach

    d = _FakeDialog()
    d.bottom = BottomPanel(QPlainTextEdit(), root=BASE)
    panel = attach(d)
    assert d.bottom.bar.count() == 5
    assert d.bottom.bar.tabText(4) == "测试"
    assert d.bottom.stack.count() == 5
    assert getattr(d, "test_panel") is panel

    d.opened = []
    panel.jumpTo.emit("core/trunk.py", 7)
    assert d.opened == [("core/trunk.py", 7)]
