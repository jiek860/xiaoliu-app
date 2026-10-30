# -*- coding: utf-8 -*-
"""问题聚合中枢（M1）：计数、摘要、信号接线。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QObject, pyqtSignal  # noqa: E402

from gui.workbench_problems import (  # noqa: E402
    ProblemsHub, aggregate_text, summary_counts,
)


class _FakeEdit(QObject):
    problemsChanged = pyqtSignal()

    def __init__(self, rows=None):
        super().__init__()
        self._rows = list(rows or [])

    def problems(self):
        return list(self._rows)

    def set_rows(self, rows):
        self._rows = list(rows)
        self.problemsChanged.emit()


def test_summary_counts_and_text():
    assert summary_counts({"a": [], "b": [(1,), (2,)]}) == (1, 2)
    assert summary_counts({}) == (0, 0)
    assert "全局 2 个（1 个文件）" in aggregate_text("a", 2, 1, 2)
    assert "全局无问题" in aggregate_text("a", 0, 0, 0)
    assert aggregate_text("a", 1, 2, 3) == "本文件 1 个问题 · 全局 3 个（2 个文件）"


def test_hub_tracks_and_emits():
    hub = ProblemsHub()
    seen = []
    hub.changed.connect(lambda: seen.append(hub.counts()))
    edit = _FakeEdit([{"line": 1}])
    hub.register("a.py", edit)
    assert hub.items("a.py") == [{"line": 1}]
    assert hub.counts() == (1, 1)
    edit.set_rows([{"line": 2}, {"line": 3}])
    assert seen and seen[-1] == (1, 2)
    assert "全局 2 个" in hub.aggregate_text("a.py")
    hub.unregister("a.py")
    assert hub.items("a.py") == []
    assert hub.counts() == (0, 0)


def test_hub_survives_broken_widget():
    hub = ProblemsHub()

    class _Broken(_FakeEdit):
        def problems(self):
            raise RuntimeError("已销毁")

    broken = _Broken()
    hub.register("b.py", broken)
    broken.set_rows([])
    assert hub.counts() == (0, 0)
