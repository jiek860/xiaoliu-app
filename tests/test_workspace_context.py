# -*- coding: utf-8 -*-
"""聊天上下文拼装：文件/选区格式与截断。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.chat import workspace_context as ctx  # noqa: E402


def test_rel_path_and_language():
    assert ctx.rel_path(os.path.join(BASE, "core", "trunk.py"), BASE) == \
        "core/trunk.py"
    assert ctx.language_of("a.py") == "python"
    assert ctx.language_of("a.unknown") == ""


def test_selection_block_has_reference_header():
    text = ctx.selection_block(
        os.path.join(BASE, "core", "trunk.py"), BASE, "x = 1\n", line=10)
    assert text.startswith("片段 core/trunk.py:10")
    assert "```python" in text and "x = 1" in text


def test_selection_block_empty_returns_blank():
    assert ctx.selection_block("a.py", BASE, "", line=1) == ""


def test_selection_block_truncates():
    text = ctx.selection_block("a.py", BASE, "x" * 5000, line=1, max_chars=300)
    assert "已截断" in text and len(text) < 5000


def test_file_block_reads_and_reports_error(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print(1)\n", encoding="utf-8")
    r = ctx.file_block(str(f), BASE, max_chars=200)
    assert r["ok"] is True and "```python" in r["text"]
    missing = ctx.file_block(str(tmp_path / "none.py"), BASE)
    assert missing["ok"] is False and missing["error"]


def test_file_block_truncates(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("y" * 5000, encoding="utf-8")
    r = ctx.file_block(str(f), BASE, max_chars=300)
    assert "已截断" in r["text"]


def test_context_block_prefers_selection(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("whole file", encoding="utf-8")
    text = ctx.context_block(str(f), BASE, selection="选中的一行", line=3)
    assert "选中的一行" in text and "whole file" not in text
    assert ctx.context_block(None, BASE) == ""


def test_prompt_with_context():
    assert ctx.prompt_with_context("干活", "") == "干活"
    assert ctx.prompt_with_context("", "代码") == "代码\n\n请阅读上面的代码。"
    out = ctx.prompt_with_context("干活", "代码")
    assert out.startswith("代码") and out.endswith("我的需求：干活")
