# -*- coding: utf-8 -*-
"""运行时依赖对账：**代码里 import 的第三方库，exe 依赖集里必须有**（或声明可选）。

为什么需要这道门禁
------------------
2026-10-27 一天之内踩了 4 次同一个坑：openpyxl → python-pptx → pypdf →
python-docx。它们都在 `core/document_parser.py` 里被 `try/except ImportError`
包着，所以：

    CI 全绿（测试环境装了这些包，代码自己也会降级）
    ↓
    源码版好用（本机 documents 全套都在）
    ↓
    **exe 缺件**（`Windows Build` 只装 requirements-runtime.lock +
    requirements-build.lock）→ 用户一用就"缺少依赖"

问题不在谁疏忽，而在**没有一道检查把"代码要什么"和"exe 带什么"对账**。
本工具就是那道检查：扫 core/gui/modules 里所有 import，逐个对
`requirements-runtime.lock`；确实装不进 exe 的（要外部程序、体积太大、
只有源码版用）必须在 `tools/runtime_import_policy.json` 的
`external_optional` 里**登记并写清缺了会怎样**，否则照样失败。

用法
----
    py -3 tools\\check_runtime_imports.py           # 人看的报告
    py -3 tools\\check_runtime_imports.py --json    # 机器读

退出码：0 全对上；1 有缺件或未登记。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_PATH = os.path.join(BASE, "requirements-runtime.lock")
POLICY_PATH = os.path.join(BASE, "tools", "runtime_import_policy.json")
SCAN_DIRS = ("core", "gui", "modules")

# 标准库 + 解释器内置；sys.stdlib_module_names 在 3.10+ 才有，兜底空集合
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}

_DIST_SPLIT = re.compile(r"[=<>!~\[; ]")


def load_lock(path=LOCK_PATH):
    """读依赖集，返回小写发行包名集合（去掉 ==版本、注释、-r 行）"""
    names = set()
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = _DIST_SPLIT.split(line, 1)[0].strip().lower()
            if name:
                names.add(name)
    return names


def load_policy(path=POLICY_PATH):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def scan_file(path):
    """返回 [(顶层模块名, 行号)]；语法错的源文件跳过（由语法门禁负责）"""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read())
    except (SyntaxError, OSError):
        return []
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hits.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                hits.append((node.module.split(".")[0], node.lineno))
    return hits


def _is_skipped(rel, skip_dirs):
    rel = rel.replace("\\", "/")
    return any(rel == d or rel.startswith(d + "/") for d in skip_dirs)


def scan_tree(base=BASE, dirs=SCAN_DIRS, skip_dirs=()):
    """{模块名: [(相对路径, 行号), ...]}"""
    hits = {}
    for sub in dirs:
        root = os.path.join(base, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, files in os.walk(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, base)
                if _is_skipped(rel, skip_dirs):
                    continue
                for mod, line in scan_file(path):
                    if mod in STDLIB:
                        continue
                    hits.setdefault(mod, []).append((rel, line))
    return hits


def classify(hits, lock, policy):
    """把扫到的模块分成三堆：在依赖集 / 已声明可选 / 缺件"""
    local = set(policy.get("local_packages") or [])
    mapping = policy.get("module_to_dist") or {}
    optional = policy.get("external_optional") or {}
    in_lock, allowed, missing = [], [], []
    for mod in sorted(hits):
        if mod in local:
            continue
        dist = str(mapping.get(mod) or mod).lower()
        if dist in lock:
            in_lock.append(mod)
        elif mod in optional:
            allowed.append({"模块": mod, "原因": str(optional[mod]),
                            "位置": hits[mod][:3]})
        else:
            missing.append({"模块": mod, "发行名": dist,
                            "已登记映射": mod in mapping,
                            "位置": hits[mod][:5]})
    return {"在依赖集": in_lock, "已声明可选": allowed, "缺件": missing,
            "扫描模块数": len(hits)}


def check(base=BASE, lock_path=None, policy_path=None):
    # 不传路径时按 base 推 —— 这样传别的仓库根目录也能正确对账
    lock_path = lock_path or os.path.join(base, "requirements-runtime.lock")
    policy_path = policy_path or os.path.join(
        base, "tools", "runtime_import_policy.json")
    policy = load_policy(policy_path)
    lock = load_lock(lock_path)
    hits = scan_tree(base, SCAN_DIRS, tuple(policy.get("skip_dirs") or ()))
    res = classify(hits, lock, policy)
    res["依赖集条目数"] = len(lock)
    res["ok"] = not res["缺件"]
    return res


def render(res):
    lines = ["运行时依赖对账（exe 依赖集 requirements-runtime.lock，%d 个发行包）"
             % res.get("依赖集条目数", 0),
             "扫描 core/ gui/ modules/：%d 个第三方模块" % res.get("扫描模块数", 0),
             "  在依赖集里：%d" % len(res.get("在依赖集") or []),
             "  已声明可选：%d（缺了只影响对应功能）" % len(res.get("已声明可选") or [])]
    if res.get("缺件"):
        lines.append("  [X] 缺件 %d 个（exe 里一定 ImportError）：" % len(res["缺件"]))
        for item in res["缺件"]:
            where = ", ".join("%s:%d" % (p, n) for p, n in item["位置"])
            hint = "" if item["已登记映射"] else "（没有模块→发行名映射，先补 policy）"
            lines.append("      %s（发行名 %s）← %s%s"
                         % (item["模块"], item["发行名"], where, hint))
        lines.append("      → 加进 requirements-runtime.lock，或在 "
                     "tools/runtime_import_policy.json 的 external_optional "
                     "里登记并写清理由")
    else:
        lines.append("  [OK] 没有缺件")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="运行时依赖对账门禁")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)
    res = check(args.base)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for line in render(res):
            print(line)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
