# -*- coding: utf-8 -*-
"""C1 符号级 diff / 影响面 单元测试（功能深化二期）。"""
from core.code_symbol_diff import impact_scan, symbols_diff


def test_symbols_diff_add_remove_change():
    before = "def a():\n    pass\n\nclass B:\n    pass\n"
    after = "def a():\n    x = 1\n    return x\n\ndef c():\n    pass\n"
    d = symbols_diff(before, after, ".py")
    added = {x["name"] for x in d["added"]}
    removed = {x["name"] for x in d["removed"]}
    assert "c" in added
    assert "B" in removed
    assert any(x["name"] == "a" for x in d["changed"])


def test_symbols_diff_empty():
    d = symbols_diff("", "", ".py")
    assert d == {"added": [], "removed": [], "changed": []}


def test_impact_scan(tmp_path):
    (tmp_path / "m.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "user.py").write_text(
        "from m import target\ntarget()\n", encoding="utf-8")
    hits = impact_scan(str(tmp_path), "target")
    files = {h["file"] for h in hits}
    assert "user.py" in files


def test_impact_scan_empty_name(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    assert impact_scan(str(tmp_path), "") == []