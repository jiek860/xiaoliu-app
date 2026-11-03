# -*- coding: utf-8 -*-
"""死代码 / 死模块 / 重复实现 审计（只读，不改任何文件）

为什么不用 ruff 之类的现成工具
------------------------------
它们查不出这个仓库最典型的三类问题：
    ① 模块登记了（LAZY_MAP / 清单里），但**全项目没有一处调用** —— 幽灵模块；
    ② 顶层函数/类写了，但只有它自己文件里出现名字（自引用不算用）；
    ③ 两份"同一功能"的实现（cache、memory、settings 计数…）各演进各的。

做法（静态近似，结果是"可疑清单"，最后一定要人工确认）
--------------------------------------------------------
    · 名字引用：把所有 .py 读成文本（去掉注释/字符串里的干扰较难，故用
      **词边界匹配**），统计每个顶层 def/class 名字在**其他文件**里出现几次。
      0 次 = 可疑死函数（同名且语义不同的情况很少，人工看一眼即可）。
    · 死模块：core/gui 每个 .py 的模块名，是否被别的文件 import / 在
      LAZY_MAP 登记 / 在 gui 里作为页面注册；都没有 = 可疑死模块。
    · 重复实现：顶层函数按"去注释、去 docstring、去空白"后的 body 哈希，
      跨文件撞哈希 = 完全相同的实现（≥6 条语句才算，避免小 utils 噪音）。

已知保留（KEEP）
----------------
有些"零引用"是**有意的公共入口**（测试重定向、插件约定、尚未接线的功能半边），
删了会丢能力或破坏约定。这些登记在 KEEP 里单独列出，不算可疑死代码 ——
真正要清的必须是 KEEP 之外、复核确认无人用的。

用法
----
    py -3 tools\\audit_dead_code.py            # 摘要 + 前 20 条
    py -3 tools\\audit_dead_code.py --all      # 全量打印
    py -3 tools\\audit_dead_code.py --json     # 机器可读（给方案文档引用）
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import sys
import tokenize

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ("core", "core/pipeline", "gui", "gui/mixins", "modules/installed",
        "modules/support", "tools", "tests")
# 根目录的入口脚本也要算进来：它们才是"真正的调用方"。
# 之前漏了这几个，`run.py::_validate_config()` 里的
# `from core.config import validate_config` 就没被统计到，
# validate_config 被误报成死函数（差点被删）。
ROOT_FILES = ("run.py", "run_server.py", "build_release.py",
              "sign_release.py", "lint_check.py")

# 复核确认"零引用但必须留"的公共入口（详见各文件 docstring）
KEEP = {
    "core/code/code_search.py::index_code":
        "语义检索的写半边，目前无人调用但删了能力就彻底没入口（待接线）",
    "core/data_paths.py::set_data_dir":
        "测试/离线脚本重定向数据的公共入口（docs/30 有约定）",
    "core/data_paths.py::clear_data_dir":
        "set_data_dir 的配对清理入口",
    "core/data_paths.py::plugin_dir":
        "插件持久化目录 data/plugin_data/<插件名> 的约定入口",
}
SKIP_NAME = re.compile(
    r"^(__.*__|main|setup|teardown|paintEvent|resizeEvent|showEvent|hideEvent|"
    r"closeEvent|keyPressEvent|mousePressEvent|mouseReleaseEvent|"
    r"mouseMoveEvent|wheelEvent|enterEvent|leaveEvent|dragEnterEvent|"
    r"dropEvent|eventFilter|event|sizeHint|minimumSizeHint|retranslateUi)$")


def _rel(p):
    return os.path.relpath(p, BASE).replace("\\", "/")


def _files():
    for n in ROOT_FILES:
        p = os.path.join(BASE, n)
        if os.path.isfile(p):
            yield p
    for d in SCAN:
        top = os.path.join(BASE, d.replace("/", os.sep))
        if not os.path.isdir(top):
            continue
        for root, dirs, names in os.walk(top):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in sorted(names):
                if n.endswith(".py"):
                    yield os.path.join(root, n)


def _texts():
    out = {}
    for p in _files():
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                out[_rel(p)] = f.read()
        except OSError:
            continue
    return out


def _blank(lines, srow, scol, erow, ecol):
    """把一段源码区间改成空白（保留行结构，行号不变）"""
    if srow == erow:
        line = lines[srow - 1]
        lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
        return
    lines[srow - 1] = lines[srow - 1][:scol]
    for r in range(srow + 1, erow):
        lines[r - 1] = ""
    tail = lines[erow - 1]
    lines[erow - 1] = " " * ecol + tail[ecol:]


def _docstring_spans(tree):
    """返回所有 docstring 的起始 (行, 列) —— 只清"第一句就是字符串"那种

    为什么不用"看到三引号就吞到下一个三引号"的老写法：
    那样一旦 docstring 和字符串字面量混在一起，状态机就会错位，
    把后面整段**真实代码**当成字符串清空（core/mcp_stdio.py 就是这样
    把 `atexit.register(_cleanup_all)` 清没了，导致 3 个函数被误判成死代码）。
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        val = first.value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            out.add((val.lineno, val.col_offset))
    return out


def _strip_comments(src):
    """去掉 # 注释和 docstring。

    **不要连字符串字面量一起抹掉**：本仓库大量按名字分发
    （`trunk.call("gpu_detector")`、`core_caps` 里的 `"method": "detect"`），
    把字符串抹了会把"字符串反射调用"误判成死代码。
    所以这里只清两类：tokenize 认出来的 COMMENT，以及 AST 认定的 docstring。
    """
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:      # 解析不了就当没有 docstring，只清注释
        tree = None
    docs = _docstring_spans(tree) if tree is not None else set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        toks = []
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            _blank(lines, tok.start[0], tok.start[1],
                   tok.end[0], tok.end[1])
        elif tok.type == tokenize.STRING and tok.start in docs:
            _blank(lines, tok.start[0], tok.start[1],
                   tok.end[0], tok.end[1])
    return "\n".join(lines)


def _toplevel(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return [], []
    defs, body_hash = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.append((node.name, node.lineno,
                         "class" if isinstance(node, ast.ClassDef) else "def"))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stmts = len(node.body)
            if stmts >= 6:
                clone = ast.Module(body=node.body, type_ignores=[])
                try:
                    dump = ast.dump(clone, annotate_fields=False)
                except TypeError:
                    dump = ast.dump(clone)
                body_hash.append((node.name, node.lineno, stmts, dump))
    return defs, body_hash


def audit():
    texts = _texts()
    clean = {k: _strip_comments(v) for k, v in texts.items()}
    # 一次性把每个文件的"出现过的标识符集合"建出来：
    # 逐个 def 去扫全仓文本是 O(def × 文件 × 文本长度)，实测跑不完；
    # 建集合之后每次查引用只是一次哈希查找。
    # 注意排除本文件自己：KEEP 表里写着候选名字，否则它们会被自己"引用"而漏报。
    self_rel = _rel(os.path.abspath(__file__))
    idents = {rel: set(re.findall(r"[A-Za-z_]\w*", c))
              for rel, c in clean.items() if rel != self_rel}

    lazy = {}
    try:
        sys.path.insert(0, BASE)
        from core.lazy_config import LAZY_MAP
        lazy = {v[0]: k for k, v in LAZY_MAP.items()}
    except Exception as e:      # 审计工具自己不静默：报出来继续
        print("[!] 读不到 LAZY_MAP：%s: %s" % (type(e).__name__, e), file=sys.stderr)

    dead_modules = []
    for rel, text in sorted(clean.items()):
        if not rel.startswith(("core/", "gui/")):
            continue
        name = os.path.basename(rel)[:-3]
        if name in ("__init__", "conftest") or name in lazy:
            continue
        where = {r for r, s in idents.items() if r != rel and name in s}
        if not where:
            dead_modules.append({"file": rel, "lines": text.count("\n") + 1})

    # 顶层 def/class 引用统计
    # 判定口径：**外部文件引用 0 次，且本文件里除定义那一行外再没出现过**。
    # 只在同一文件被调用（调度表/顺带调用）不算死代码，所以要把本文件出现数算进来。
    dead_defs = []
    kept_defs = []
    for rel in sorted(clean):
        if rel.startswith(("tests/", "tools/")) or "/" not in rel:
            # pytest / 命令行按名字发现，根目录入口脚本本身就是入口，都不算死代码
            continue
        path = os.path.join(BASE, rel.replace("/", os.sep))
        defs, _ = _toplevel(path)
        if not defs:
            continue
        body = clean[rel]
        for name, line, kind in defs:
            if SKIP_NAME.match(name):
                continue
            own = len(re.findall(r"\b%s\b" % re.escape(name), body))
            hits = sum(1 for other, s in idents.items()
                       if other != rel and name in s)
            if hits == 0 and own <= 1:
                item = {"file": rel, "line": line, "kind": kind,
                        "name": name,
                        "private": name.startswith("_")}
                key = "%s::%s" % (rel, name)
                if key in KEEP:
                    item["why"] = KEEP[key]
                    kept_defs.append(item)
                else:
                    dead_defs.append(item)

    # 重复实现
    seen = {}
    dups = []
    for rel in sorted(clean):
        path = os.path.join(BASE, rel.replace("/", os.sep))
        _, hashes = _toplevel(path)
        for name, line, stmts, dump in hashes:
            key = hash(dump)
            if key in seen:
                prev_rel, prev_name, prev_line, prev_n = seen[key]
                if prev_rel != rel:
                    dups.append({"a": "%s:%d %s" % (prev_rel, prev_line, prev_name),
                                 "b": "%s:%d %s" % (rel, line, name),
                                 "statements": stmts})
            else:
                seen[key] = (rel, name, line, stmts)

    return {"dead_modules": dead_modules, "dead_defs": dead_defs,
            "kept_defs": kept_defs,
            "duplicates": dups, "scanned": len(clean)}


def main():
    ap = argparse.ArgumentParser(description="死代码 / 死模块 / 重复实现审计")
    ap.add_argument("--all", action="store_true", help="打印全部结果")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    r = audit()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    n = 20 if not args.all else 10 ** 6
    print("=" * 72)
    print("扫描 %d 个 .py" % r["scanned"])
    print("可疑死模块 %d 个 / 可疑死函数类 %d 个 / 已知保留 %d 个 / 完全重复实现 %d 组"
          % (len(r["dead_modules"]), len(r["dead_defs"]),
             len(r["kept_defs"]), len(r["duplicates"])))
    print("=" * 72)
    if r["dead_modules"]:
        print("\n【可疑死模块】")
        for x in r["dead_modules"][:n]:
            print("  %-42s %4d 行" % (x["file"], x["lines"]))
    if r["dead_defs"]:
        print("\n【可疑死函数/类】（只有自己文件里出现名字）")
        for x in r["dead_defs"][:n]:
            print("  %-38s:%-5d %s %s" % (x["file"], x["line"],
                                          x["kind"], x["name"]))
    if r["kept_defs"]:
        print("\n【已知保留】（KEEP 登记：零引用但是有意的公共入口）")
        for x in r["kept_defs"][:n]:
            print("  %-38s:%-5d %s  ← %s" % (x["file"], x["line"],
                                             x["name"], x["why"]))
    if r["duplicates"]:
        print("\n【完全重复实现】")
        for x in r["duplicates"][:n]:
            print("  %d 条语句  %s\n            ==  %s"
                  % (x["statements"], x["a"], x["b"]))
    print("\n注意：静态近似，" + "可疑" + "≠" + "确定死" + "；改名/反射/字符串拼装调用查不到，需人工确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
