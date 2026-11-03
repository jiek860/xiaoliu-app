# -*- coding: utf-8 -*-
"""报错提示：异常类型 -> 可执行建议。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code import error_hints  # noqa: E402


def test_hint_for_known_type():
    hint = error_hints.hint_for("ModuleNotFoundError: No module named 'requests'")
    assert "组件" in hint


def test_hint_for_indentation_and_permission():
    assert "缩进" in error_hints.hint_for("IndentationError: unexpected indent")
    assert "权限" in error_hints.hint_for("PermissionError: [Errno 13]")


def test_hint_for_unknown_returns_empty():
    assert error_hints.hint_for("some random output") == ""
    assert error_hints.lines_for("some random output") == []


def test_hint_for_pattern_when_type_unknown():
    assert "端口" in error_hints.hint_for("OSError: [Errno 98] "
                                         "Address already in use")


def test_lines_for_prefixes_hint():
    lines = error_hints.lines_for("ZeroDivisionError: division by zero")
    assert lines and lines[0].startswith("💡 ")


# ---------------------------------------------------------------- 第 8 批 B5
TRACEBACK = ('Traceback (most recent call last):\n'
             '  File "core/app.py", line 12, in main\n'
             '    run()\n'
             'ZeroDivisionError: division by zero\n')


def test_locations_dedupes_file_line():
    """同一处报错在 traceback 里出现两次，问题页只该有一条。"""
    found = error_hints.locations(TRACEBACK + TRACEBACK)
    assert found == [{"file": "core/app.py", "line": 12, "symbol": ""}]


def test_locations_reads_bare_path_line():
    """编译输出常见 ``x.py:12: msg`` 形式（没有 File "..." 外壳）。"""
    found = error_hints.locations("core/app.py:12: ZeroDivisionError")
    assert [x["line"] for x in found] == [12]


def test_locations_handles_empty_output():
    assert error_hints.locations("") == []
    assert error_hints.locations("all good\n") == []


def test_locations_attach_symbol_from_project(tmp_path):
    """有项目根时补上函数名，回修提示才能写「在 xx 里出错」。"""
    pkg = tmp_path / "core"
    pkg.mkdir()
    body = "def main():\n" + "".join(
        "    x%d = %d\n" % (i, i) for i in range(1, 20))
    (pkg / "app.py").write_text(body, encoding="utf-8")
    found = error_hints.locations(TRACEBACK, str(tmp_path))
    assert found[0]["symbol"] == "main"


def test_problems_from_text_feeds_problem_page():
    rows = error_hints.problems_from_text(TRACEBACK)
    assert rows == [(12, 1, "运行", "运行时报错")]


def test_problems_from_text_filters_other_files():
    """跑一个文件时，问题页不该冒出别的文件的报错。"""
    assert error_hints.problems_from_text(TRACEBACK, "gui/x.py") == []
    same = error_hints.problems_from_text(TRACEBACK, "./core/app.py")
    assert len(same) == 1


def test_problems_from_text_names_the_symbol(tmp_path):
    pkg = tmp_path / "core"
    pkg.mkdir()
    body = "def main():\n" + "".join(
        "    x%d = %d\n" % (i, i) for i in range(1, 20))
    (pkg / "app.py").write_text(body, encoding="utf-8")
    rows = error_hints.problems_from_text(TRACEBACK, "", str(tmp_path))
    assert rows[0][3] == "在 main 里出错"


def test_lines_for_adds_location_rows():
    lines = error_hints.lines_for(TRACEBACK)
    assert lines[0].startswith("💡 ")
    assert lines[1] == "📍 core/app.py:12"

