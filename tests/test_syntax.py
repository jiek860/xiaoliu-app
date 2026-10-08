# -*- coding: utf-8 -*-
"""测试：全项目语法检查（含 modules_repo 镜像目录与其余自研目录）"""
import os
import compileall

DIRS = ["core", "gui", "modules/installed", "modules_repo",
        "plugins", "tools", "scripts"]


def test_syntax():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    failed = []
    for d in DIRS:
        path = os.path.join(root, d)
        if not os.path.isdir(path):
            continue
        if not compileall.compile_dir(path, quiet=1):
            failed.append(d)
    assert not failed, f"{failed} 存在语法错误"
