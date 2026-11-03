# -*- coding: utf-8 -*-
"""第 8 批 B5 + 深度⑧⑨：静态检查的纯逻辑（命令、解析、多源合并）。"""
import json
import sys

from core.code import lint


def _fake_ruff_output(tmp_path):
    sample = [{"code": "F401", "message": "`os` imported but unused",
               "location": {"row": 2, "column": 8}}]
    return json.dumps(sample)


def test_ruff_command_uses_path_ruff_or_python_module(monkeypatch):
    monkeypatch.setattr(lint.shutil, "which", lambda _n: "C:/bin/ruff.exe")
    assert lint.ruff_base() == ["C:/bin/ruff.exe"]
    cmd = lint.ruff_command("x.py")
    assert cmd[0] == "C:/bin/ruff.exe"
    assert cmd[-2:] == ["--", "x.py"]

    monkeypatch.setattr(lint.shutil, "which", lambda _n: None)
    assert lint.ruff_base() == [sys.executable, "-m", "ruff"]
    stdin_cmd = lint.ruff_stdin_command("x.py")
    assert "--stdin-filename" in stdin_cmd
    assert stdin_cmd[stdin_cmd.index("--stdin-filename") + 1] == "x.py"
    assert stdin_cmd[-1] == "-"


def test_parse_ruff_json_tolerates_junk():
    sample = ('[{"code":"F401","message":"m",'
              '"location":{"row":3,"column":8}}]')
    assert lint.parse_ruff_json(sample) == [(3, 8, "F401", "m")]
    assert lint.parse_ruff_json("") is None
    assert lint.parse_ruff_json("不是 JSON") is None
    assert lint.parse_ruff_json('{"not": "a list"}') is None
    # 缺 location 的条目按第 1 行兜底，不让整批解析失败
    assert lint.parse_ruff_json('[{"code":"X"}]') == [(1, 1, "X", "")]


def test_ast_problems_reports_first_syntax_error():
    rows = lint.ast_problems("def broken(:\n")
    assert rows and rows[0][0] == 1 and rows[0][2] == "SyntaxError"
    assert lint.ast_problems("x = 1\n") == []


def test_live_ruff_checks_unsaved_text(monkeypatch):
    """深度⑨：实时检查读的是编辑器里的文本，不是磁盘上的旧内容。"""
    script = "import json,sys; print(%r)" % _fake_ruff_output(None)
    monkeypatch.setattr(lint, "ruff_stdin_command",
                        lambda _p: [sys.executable, "-c", script])
    rows = lint.live_ruff("import os\n", "x.py")
    assert rows == [(2, 8, "F401", "`os` imported but unused")]


def test_live_ruff_skips_non_python():
    assert lint.live_ruff("let x = 1;", "app.js") is None


def test_live_ruff_returns_none_when_ruff_missing(monkeypatch):
    monkeypatch.setattr(lint, "ruff_stdin_command",
                        lambda _p: ["no-such-ruff-binary-xyz"])
    assert lint.live_ruff("x = 1\n", "x.py") is None


def test_lsp_rows_filters_severity_and_missing_range():
    diagnostics = {
        "file:///C:/proj/core/a.py": [
            {"severity": 1, "source": "pyright", "message": "错误的类型",
             "range": {"start": {"line": 4, "character": 2}}},
            {"severity": 2, "source": "ruff", "message": "未使用",
             "range": {"start": {"line": 9, "character": 0}}},
            {"severity": 3, "source": "pyright", "message": "信息",
             "range": {"start": {"line": 11, "character": 3}}},
            {"severity": 1, "message": "没有定位"},
        ],
        "file:///C:/proj/other.py": [
            {"severity": 1, "message": "别的文件",
             "range": {"start": {"line": 2, "character": 1}}},
        ],
    }
    rows = lint.lsp_rows(diagnostics, "C:/proj/core/a.py")
    assert rows == [(5, 3, "LSP·pyright", "错误的类型"),
                    (10, 1, "LSP·ruff", "⚠ 未使用")]


def test_lsp_rows_accepts_plain_paths_and_relative_targets():
    diagnostics = {"core/a.py": [
        {"severity": 1, "message": "m",
         "range": {"start": {"line": 0, "character": 0}}}]}
    assert lint.lsp_rows(diagnostics, "a.py") == [(1, 1, "LSP·LSP", "m")]


def test_merge_problems_prefers_non_empty_highest_priority():
    lsp = [(1, 1, "LSP·x", "lsp")]
    ruff = [(2, 1, "F401", "ruff")]
    ast = [(3, 1, "SyntaxError", "ast")]
    assert lint.merge_problems([], [], ast) == ast
    assert lint.merge_problems([], ruff, ast) == ruff
    assert lint.merge_problems(lsp, ruff, ast) == lsp
    assert lint.merge_problems(None, None, None) == []


def test_status_reports_channels():
    info = lint.status()
    assert info["来源"] == ["LSP", "ruff", "ast"]
    assert "可用" in info and "ruff" in info
