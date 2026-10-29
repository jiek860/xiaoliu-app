# -*- coding: utf-8 -*-
"""调用图与测试映射（批次 45.2）：callers_of / callees_of / tests_for。"""
import os

from core.code.index_v2 import CodeIndexV2


def _write(root, rel, text):
    path = os.path.join(str(root), rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)
    return path


def _index(tmp):
    _write(tmp, "core/util.py",
           "def helper():\n    return 1\n\n"
           "def wrapper():\n    return helper()\n")
    _write(tmp, "core/svc.py",
           "from core.util import helper\n\n"
           "class Svc:\n"
           "    def run(self):\n"
           "        return helper()\n")
    _write(tmp, "tests/test_util.py",
           "from core.util import helper\n\n"
           "def test_helper():\n    assert helper() == 1\n")
    _write(tmp, "tests/test_svc.py",
           "from core.svc import Svc\n\n"
           "def test_run():\n    assert Svc\n")
    index = CodeIndexV2(str(tmp), str(tmp))
    index.refresh()
    return index


def test_callers_of_function(tmp_path):
    index = _index(tmp_path)
    assert "wrapper" in index.callers_of("helper")
    assert "run" in index.callers_of("helper")


def test_callees_of_function(tmp_path):
    index = _index(tmp_path)
    assert index.callees_of("wrapper") == ["helper"]
    assert index.callees_of("run") == ["helper"]


def test_module_level_call_attributed_to_module(tmp_path):
    _write(tmp_path, "boot.py", "helper()\n")
    index = CodeIndexV2(str(tmp_path), str(tmp_path))
    index.refresh()
    assert "<module>" in index.callers_of("helper")


def test_method_call_is_recorded_by_method_name(tmp_path):
    _write(tmp_path, "core/client.py",
           "class C:\n"
           "    def a(self):\n"
           "        return self.b()\n"
           "    def b(self):\n"
           "        return 1\n")
    index = CodeIndexV2(str(tmp_path), str(tmp_path))
    index.refresh()
    assert index.callees_of("a") == ["b"]
    assert "a" in index.callers_of("b")


def test_tests_for_import_reverse(tmp_path):
    index = _index(tmp_path)
    assert index.tests_for("core/util.py") == ["tests/test_util.py"]
    assert index.tests_for("core/svc.py") == ["tests/test_svc.py"]


def test_unknown_names_return_empty(tmp_path):
    index = _index(tmp_path)
    assert index.callers_of("nope") == []
    assert index.callees_of("nope") == []
    assert index.tests_for("nope.py") == []
