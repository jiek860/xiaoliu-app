# -*- coding: utf-8 -*-
"""代码索引 v2（批次 45.1）：函数级分块、FTS5 检索、增量刷新、跳过超大文件。"""
import os

from core.code.index_v2 import CodeIndexV2

SOURCE = '''\
def helper(x):
    return x + 1


class Calc:
    def run(self, value):
        return helper(value)
'''


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def _project(tmp):
    _write(tmp, "mod.py", SOURCE)
    _write(tmp, "src/thing.py", "def thing():\n    return 1\n")
    _write(tmp, "tests/test_mod.py",
           "from mod import helper\n\ndef test_helper():\n    assert helper(1)\n")
    return CodeIndexV2(str(tmp), str(tmp))


def test_refresh_indexes_files_and_chunks(tmp_path):
    index = _project(tmp_path)
    stats = index.refresh()
    assert stats["ok"] is True
    assert stats["files"] >= 3
    assert stats["chunks"] >= 3
    assert index.stats()["files"] >= 3


def test_outline_has_function_and_class(tmp_path):
    index = _project(tmp_path)
    index.refresh()
    names = {item["symbol"] for item in index.outline("mod.py")}
    assert {"helper", "Calc", "run"} <= names


def test_search_finds_symbol_chunk(tmp_path):
    index = _project(tmp_path)
    index.refresh()
    hits = index.search("helper")
    assert hits
    assert any(h["path"] == "mod.py" and h["symbol"] == "helper"
               and h["start_line"] >= 1 for h in hits)


def test_second_refresh_is_incremental(tmp_path):
    index = _project(tmp_path)
    first = index.refresh()
    second = index.refresh()
    assert second["updated"] == 0
    assert second["skipped"] == first["files"]
    assert second["seconds"] <= first["seconds"] + 1.0


def test_changed_file_is_reindexed(tmp_path):
    index = _project(tmp_path)
    index.refresh()
    _write(tmp_path, "mod.py", SOURCE + "\n\ndef extra():\n    return 2\n")
    stats = index.refresh()
    assert stats["updated"] == 1
    assert index.search("extra")


def test_deleted_file_is_removed(tmp_path):
    index = _project(tmp_path)
    index.refresh()
    os.remove(os.path.join(str(tmp_path), "src", "thing.py"))
    stats = index.refresh()
    assert stats["removed"] == 1
    assert index.outline("src/thing.py") == []
    assert index.search("thing") == []


def test_oversized_file_is_skipped(tmp_path, monkeypatch):
    import core.code.index_v2 as mod
    monkeypatch.setattr(mod, "MAX_FILE_BYTES", 200)
    _write(tmp_path, "big.py", "def huge():\n" + "    x = 1\n" * 80)
    index = CodeIndexV2(str(tmp_path), str(tmp_path))
    index.refresh()
    assert index.outline("big.py") == []
    assert index.search("huge") == []


def test_broken_python_falls_back_to_module_chunk(tmp_path):
    _write(tmp_path, "broken.py", "def x(:\n  pass\n")
    index = CodeIndexV2(str(tmp_path), str(tmp_path))
    index.refresh()
    outline = index.outline("broken.py")
    assert outline and outline[0]["kind"] == "module"


def test_empty_query_and_disabled_index_are_safe(tmp_path):
    index = _project(tmp_path)
    index.refresh()
    assert index.search("") == []
    index.ok = False
    assert index.search("helper") == []
    assert index.refresh()["ok"] is False
