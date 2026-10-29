# -*- coding: utf-8 -*-
"""批次 46.5：内联编辑的纯函数部分（选区/函数定位、替换内容解析）。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.patch_protocol import function_span  # noqa: E402
from gui.code_editor_ai import _extract_new, _line_offsets  # noqa: E402

CODE = ("import os\n\n"
        "def foo():\n"
        "    value = 1\n"
        "    return value\n\n"
        "def bar():\n"
        "    return 2\n")


def test_line_offsets_cover_every_line():
    offsets = _line_offsets(CODE)
    assert offsets[0] == 0
    assert offsets[-1] == len(CODE)
    assert CODE[offsets[0]:offsets[1]] == "import os\n"


def test_function_scope_offsets_extract_only_that_function():
    span = function_span(CODE, 4)
    offsets = _line_offsets(CODE)
    start, end = offsets[span["start"] - 1], offsets[span["end"]]
    snippet = CODE[start:end]
    assert snippet.startswith("def foo")
    assert "return value" in snippet
    assert "def bar" not in snippet


def test_function_scope_last_function_end():
    span = function_span(CODE, 8)
    offsets = _line_offsets(CODE)
    start, end = offsets[span["start"] - 1], offsets[span["end"]]
    assert CODE[start:end].startswith("def bar")
    assert end <= len(CODE)


def test_extract_new_from_json():
    assert _extract_new('{"new": "value = 2", "reason": "fix"}') == "value = 2"


def test_extract_new_from_code_block():
    text = "说明\n```python\ndef foo():\n    return 3\n```\n"
    assert _extract_new(text) == "def foo():\n    return 3\n"


def test_extract_new_returns_empty_for_plain_text():
    assert _extract_new("我觉得这里应该改成 2") == ""


def test_extract_new_tolerates_broken_json():
    assert _extract_new('{"new": ') == ""


def test_minimal_hunks_round_trip_on_multi_change():
    from core.patch_protocol import minimal_hunks
    old = "".join("line%d\n" % i for i in range(12))
    new = old.replace("line2\n", "LINE2\n").replace("line9\n", "LINE9\n")
    hunks = minimal_hunks(old, new)
    assert len(hunks) >= 1
    rebuilt = old
    for hunk in hunks:
        assert rebuilt.count(hunk["old"]) == 1
        rebuilt = rebuilt.replace(hunk["old"], hunk["new"], 1)
    assert rebuilt == new
