# -*- coding: utf-8 -*-
"""真符号索引测试：Python AST、JS/TS 解析与检索排序。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.symbol_parser import parse_python, parse_source  # noqa: E402
from core.workspace_index import WorkspaceIndex  # noqa: E402


def test_python_ast_kinds_and_nested(tmp_path):
    p = tmp_path / "m.py"
    p.write_text(
        "class Foo:\n"
        "    async def method(self):\n"
        "        def inner():\n"
        "            pass\n"
        "        return inner\n\n"
        "def top():\n"
        "    def nested():\n"
        "        pass\n", encoding="utf-8")
    r = parse_python(str(p), "m.py")
    kinds = {(s["name"], s["kind"]) for s in r["symbols"]}
    assert ("Foo", "class") in kinds
    assert ("Foo.method", "method") in kinds
    assert ("Foo.method.inner", "nested_function") in kinds
    assert ("top", "function") in kinds
    assert ("top.nested", "nested_function") in kinds
    assert all(s["engine"] == "ast" for s in r["symbols"])
    assert next(s for s in r["symbols"] if s["name"] == "Foo.method")["async"] is True


def test_js_regex_symbols_and_imports(tmp_path):
    p = tmp_path / "app.ts"
    p.write_text(
        "import { x } from './util';\n"
        "export class Store {}\n"
        "export function load() {}\n"
        "const save = async (v) => v;\n"
        "interface Row { id: number }\n"
        "type Key = string;\n", encoding="utf-8")
    r = parse_source(str(p), "app.ts")
    names = {s["name"] for s in r["symbols"]}
    assert {"Store", "load", "save", "Row", "Key"} <= names
    assert "./util" in r["imports"]
    assert r["meta"]["symbol_engine"] in ("regex", "tree-sitter")
    if r["meta"]["symbol_engine"] == "regex":
        assert all(s["confidence"] == 0.6 for s in r["symbols"])
    assert r["meta"]["language"] == "typescript"


def test_find_symbols_ranks_exact_first_and_filters(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text(
        "class Domain:\n    def run(self):\n        pass\n\n"
        "def main():\n    pass\n", encoding="utf-8")
    (root / "b.ts").write_text("export function mainTask() {}\n",
                               encoding="utf-8")
    idx = WorkspaceIndex(str(tmp_path / "idx"), str(root))
    stats = idx.rebuild()
    assert stats["symbols"] >= 4
    assert "ast" in stats["symbol_engines"]
    hits = idx.find_symbols("main")
    assert hits[0]["name"] == "main"
    only_class = idx.find_symbols("run", kind="method")
    assert only_class and all(h["kind"] == "method" for h in only_class)
    only_ts = idx.find_symbols("main", file="b.ts")
    assert [h["file"] for h in only_ts] == ["b.ts"]
    assert idx.find_symbols("")  # 空查询用于 outline
