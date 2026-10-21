# -*- coding: utf-8 -*-
"""插件依赖与循环依赖检查（小6插件标准 v2.1 N3.2 / N10）。

检查项：
  1. manifest.depends 语法：core:<module> / plugin:<name>@<range> / pkg:<name>@<range>
  2. 插件间依赖必须存在且已签名
  3. 环依赖检测（拓扑排序）
  4. 源码 AST 里的 core 依赖是否在 PUBLIC_CORE_MODULES 内（--ast）

用法：
    py -3 tools/check_plugin_deps.py            # 清单依赖 + 环检测
    py -3 tools/check_plugin_deps.py --ast      # 额外做源码依赖边界检查
    py -3 tools/check_plugin_deps.py --json
"""
from __future__ import annotations

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.plugin_api import validate_plugin_source  # noqa: E402

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")
SRC_DIR = os.path.join(BASE, "modules_repo")
_DEP_RE = re.compile(r"^(core|plugin|pkg):([A-Za-z0-9_.\-]+)(?:@(.+))?$")


def _load():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def parse_dep(text):
    m = _DEP_RE.match(str(text or "").strip())
    if not m:
        return None
    kind, name, rng = m.groups()
    if kind == "plugin" and not rng:
        return None
    return {"kind": kind, "name": name, "range": rng or ""}


def find_cycles(graph):
    """返回环列表（每个环是一串节点名）。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack, cycles = [], []

    def visit(node):
        color[node] = GREY
        stack.append(node)
        for nxt in graph.get(node, ()):
            if nxt not in color:
                continue
            if color[nxt] == GREY:
                i = stack.index(nxt)
                cycles.append(stack[i:] + [nxt])
            elif color[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        color[node] = BLACK

    for node in list(graph):
        if color[node] == WHITE:
            visit(node)
    return cycles


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    with_ast = "--ast" in argv
    modules = _load()
    by_name = {m.get("name"): m for m in modules}
    errors, warnings = [], []
    graph = {m.get("name"): set() for m in modules}

    for meta in modules:
        name = meta.get("name")
        for dep in meta.get("depends") or []:
            parsed = parse_dep(dep)
            if not parsed:
                errors.append("%s: depends 语法非法 %r（应为 core:/plugin:/pkg:）"
                              % (name, dep))
                continue
            if parsed["kind"] == "plugin":
                target = parsed["name"]
                if target not in by_name:
                    errors.append("%s: 依赖的插件不存在 %s" % (name, target))
                    continue
                if not str(by_name[target].get("signature") or "").strip():
                    errors.append("%s: 依赖的插件未签名 %s" % (name, target))
                graph[name].add(target)

    for cycle in find_cycles(graph):
        errors.append("循环依赖: " + " -> ".join(str(x) for x in cycle))

    if with_ast:
        for meta in modules:
            path = os.path.join(SRC_DIR, meta.get("file") or "")
            if not os.path.isfile(path):
                errors.append("%s: 源码不存在 %s" % (meta.get("name"), path))
                continue
            src = open(path, encoding="utf-8", errors="replace").read()
            r = validate_plugin_source(src, strict=not meta.get("first_party"),
                                       first_party=bool(meta.get("first_party")))
            for e in r.get("errors") or []:
                errors.append("%s: %s" % (meta.get("name"), e))

    report = {"checked": len(modules), "errors": errors[:50],
              "warnings": warnings[:50], "ok": not errors}
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("插件依赖检查（v2.1 N3.2 / N10）")
        print("=" * 70)
        print("模块 %d · error %d" % (len(modules), len(errors)))
        for e in errors[:20]:
            print("  [E] " + e)
        print()
        print("[OK] 依赖声明与循环检测通过" if not errors
              else "[X] 依赖检查未通过")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
