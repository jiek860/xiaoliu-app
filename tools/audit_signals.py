# -*- coding: utf-8 -*-
"""信号接线审计：找出"声明了 / 发射了，但从没被 connect"的 Qt 信号。

只做静态近似：按属性名收集 ``pyqtSignal`` 声明、``.emit`` 调用和
``.connect`` 调用，再按名字求差集。名字撞车（不同类里同名信号）
会合并统计，所以结果只用来"找可疑点"，最终要人工确认。

用法:
    py -3 tools\\audit_signals.py            # 打印可疑信号
    py -3 tools\\audit_signals.py --json     # 机器可读
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("core", "gui", "modules", "modules_repo", "plugins_repo",
             "plugin_repo")


def _py_files():
    for name in SCAN_DIRS:
        folder = BASE / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _attr_name(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def collect():
    declared = {}      # name -> [file:line]
    emitted = {}       # name -> [file:line]
    connected = {}     # name -> [file:line]
    for path in _py_files():
        rel = path.relative_to(BASE).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = _attr_name(node.value.func) or ""
                if fn == "pyqtSignal" and len(node.targets) == 1:
                    name = _attr_name(node.targets[0])
                    if name:
                        declared.setdefault(name, []).append(
                            "%s:%d" % (rel, node.lineno))
            elif isinstance(node, ast.Call):
                name = _attr_name(node.func)
                if isinstance(node.func, ast.Attribute) and name in (
                        "emit", "connect"):
                    target = _attr_name(node.func.value)
                    if not target:
                        continue
                    bucket = emitted if name == "emit" else connected
                    bucket.setdefault(target, []).append(
                        "%s:%d" % (rel, node.lineno))
    return declared, emitted, connected


def report():
    declared, emitted, connected = collect()
    rows = []
    for name in sorted(set(declared) | set(emitted)):
        if name in connected:
            continue
        rows.append({
            "signal": name,
            "declared": declared.get(name, [])[:3],
            "emitted": emitted.get(name, [])[:5],
            "emit_count": len(emitted.get(name, [])),
        })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qt 信号接线审计")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = report()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print("可疑信号（有声明或 emit，但没有 connect）：%d 个" % len(rows))
    for row in rows:
        print("- %s  emit=%d  声明=%s  发射=%s"
              % (row["signal"], row["emit_count"],
                 ",".join(row["declared"]) or "-",
                 ",".join(row["emitted"]) or "-"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
