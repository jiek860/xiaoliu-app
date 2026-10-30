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
