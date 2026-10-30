# -*- coding: utf-8 -*-
"""运行输出解析：异常抽取、位置、退出码文案与摘要。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.code import run_parse  # noqa: E402

TB = '''Traceback (most recent call last):
  File "core/trunk.py", line 42, in call
    return self.fn(*args)
ZeroDivisionError: division by zero
'''


def test_exceptions_extract_type_message_and_location():
    items = run_parse.exceptions(TB)
    assert items[-1]["type"] == "ZeroDivisionError"
    assert items[-1]["message"] == "division by zero"
    assert items[-1]["file"] == "core/trunk.py" and items[-1]["line"] == 42


def test_last_exception_empty_without_traceback():
    assert run_parse.last_exception("ok") == {}


def test_exceptions_ignores_traceback_header():
    types = [x["type"] for x in run_parse.exceptions(TB)]
    assert "Traceback" not in types


def test_exceptions_handles_bare_exception_line():
    items = run_parse.exceptions("ValueError: bad value\n")
    assert items[0]["type"] == "ValueError"
    assert items[0]["file"] == "" and items[0]["line"] == 0


def test_failed_locations_dedupes():
    text = 'File "a.py", line 3\nFile "a.py", line 3\nFile "b.py", line 9\n'
    found = run_parse.failed_locations(text)
    assert [(x["file"], x["line"]) for x in found] == [("a.py", 3), ("b.py", 9)]


def test_exit_text_variants():
    assert "成功" in run_parse.exit_text(0)
    assert "用法" in run_parse.exit_text(2)
    assert "Ctrl+C" in run_parse.exit_text(130)
    assert run_parse.exit_text(1).startswith("退出码 1")


def test_summary_success_and_failure():
    assert run_parse.summary("all good", 0) == "运行完成，没有报错"
    s = run_parse.summary(TB, 1)
    assert "ZeroDivisionError" in s and "core/trunk.py:42" in s
    assert run_parse.summary("", 1) == run_parse.exit_text(1)
