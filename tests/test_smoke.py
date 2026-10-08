# -*- coding: utf-8 -*-
"""基础冒烟测试：改完代码跑一遍，确保核心没坏"""
import os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# 自检覆盖范围：所有自研代码目录
# （libs/ 是第三方库，backups/data/staging 是运行时数据，都不扫）
SCAN_DIRS = ["core", "gui", "modules", "modules_repo", "plugins", "tools", "scripts"]

# 机器相关硬编码：开发机项目路径 / 开发机用户目录 / 别的项目残留路径
# 注意：C:\Program Files\... 这类是正常的程序查找路径，不算违规
BAD_PATTERNS = [
    r"E:\\xiaoliu",
    r"C:\\Users\\tt",
    r"D:\\web_agent_v2",
]


def _iter_py(d):
    root_d = os.path.join(BASE, d)
    if not os.path.isdir(root_d):
        return
    for r, dirs, fs in os.walk(root_d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(r, f)


def test_core_import():
    """核心模块能正常导入"""
    import core.trunk
    import core.llm_client
    import core.vector_store
    import core.config


def test_no_hardcoded_path():
    """自研代码（含 modules_repo 镜像目录）无机器相关硬编码路径"""
    bad = []
    for d in SCAN_DIRS:
        for fp in _iter_py(d):
            txt = open(fp, encoding="utf-8", errors="ignore").read()
            for pat in BAD_PATTERNS:
                if re.search(pat, txt):
                    bad.append("%s (%s)" % (os.path.relpath(fp, BASE), pat))
                    break
    assert not bad, "发现硬编码路径: %s" % bad


def test_all_py_compile():
    """所有自研 py 文件语法正确"""
    import py_compile
    for d in SCAN_DIRS:
        for fp in _iter_py(d):
            py_compile.compile(fp, doraise=True)


def test_lazy_map_resolvable():
    """懒加载登记的模块都能在 modules/installed 或 core 里找到，且类名对得上"""
    import ast
    from core.lazy_config import LAZY_MAP
    inst = os.path.join(BASE, "modules", "installed")
    cored = os.path.join(BASE, "core")
    missing = []
    for key, val in LAZY_MAP.items():
        fname, cls = val[0], val[1]
        hit = None
        for d in (inst, cored):
            p = os.path.join(d, fname + ".py")
            if os.path.exists(p):
                hit = p
                break
        if not hit:
            missing.append("%s -> 找不到 %s.py" % (key, fname))
            continue
        try:
            tree = ast.parse(open(hit, "rb").read())
            names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        except Exception as e:
            missing.append("%s 解析失败: %s" % (key, e))
            continue
        if cls not in names:
            missing.append("%s -> %s 里没有类 %s" % (key, os.path.basename(hit), cls))
    assert not missing, "懒加载登记有问题: %s" % missing
