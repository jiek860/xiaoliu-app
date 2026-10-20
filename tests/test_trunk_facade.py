# -*- coding: utf-8 -*-
"""锁定 core/trunk.py 为门面文件，禁止业务逻辑重新堆回去。"""
import ast
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def test_trunk_facade_line_budget_and_public_api():
    path = os.path.join(BASE, "core", "trunk.py")
    src = open(path, encoding="utf-8").read()
    assert len(src.splitlines()) <= 220, "core/trunk.py 超过 220 行，门面文件禁止继续膨胀"

    tree = ast.parse(src)
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "Trunk")
    methods = {n.name for n in cls.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert methods <= {"__init__"}, (
        "Trunk 门面里新增了业务方法: %s；请拆到 trunk_*_mixin" % sorted(methods))

    from core.trunk import Trunk
    for name in ("reply", "call", "_load_lazy", "_deep_check", "_warmup",
                 "save_config", "mem_add", "unload_idle_modules",
                 "get_task_runtime", "validate_lazy_imports"):
        assert hasattr(Trunk, name) and callable(getattr(Trunk, name)), \
            "公共 API 丢失: " + name
