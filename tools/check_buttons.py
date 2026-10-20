# -*- coding: utf-8 -*-
"""按钮预算守卫 —— 防止"顺手加个按钮"把复杂度长回去

背景
----
实测（2026-10-13）GUI 里有 114 处控件创建、27 个文件、14 个弹窗。
而 24 条入口能力里 23 条其实"说一句"就能用 —— 按钮多不是功能多，
是功能的**统一调用入口**缺失，只能一个功能配一个按钮。

本脚本把当前数量冻结成**棘轮**：只许降不许升。加了按钮就失败，
逼着先回答"为什么『说一句』替代不了它"。

用法
----
    py -3 tools\\check_buttons.py            # 检查（超预算返回 1）
    py -3 tools\\check_buttons.py --rebase   # 撤完按钮后下调基线

和 check_version.py / check_shapes.py 一样，可以挂进 check.bat。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET = os.path.join(BASE, "tools", "button_budget.json")

BTN = ("QPushButton", "QToolButton", "QRadioButton", "QCheckBox",
       "QCommandLinkButton", "QAction")

# 循环驱动的按钮表：`for ... in self.ACTIONS:` 里创建一个按钮，
# 源码只有 1 处创建语句，运行时却产出 N 个控件。
# 实测踩过这个坑：旧"实用工具"面板 1 处创建点 -> 24 个按钮，
# 只数创建点会把 24 个控件的复杂度记成 1。
TABLE_RE = re.compile(r"for\s+[^\n]*\bin\s+(?:self\.)?([A-Z_]{3,})\b")
# 表名的语义来源：只统计名字像"动作/按钮/项目"的表，避免误伤普通循环
TABLE_HINT = ("ACTION", "BUTTON", "ITEM", "ENTRY", "COMMAND", "TOOL")


def count_tables(src):
    """统计循环驱动的按钮表行数：{表名: 行数}"""
    out = {}
    for name in set(TABLE_RE.findall(src)):
        if not any(h in name for h in TABLE_HINT):
            continue
        m = re.search(r"^\s*%s\s*=\s*\[(.*?)^\s*\]" % re.escape(name),
                      src, re.S | re.M)
        if not m:
            continue
        # 顶层元组行数（以 4 空格开头的 "(" 或 "(" 起始行）
        rows = len(re.findall(r"^\s{0,8}\(", m.group(1), re.M))
        if rows:
            out[name] = rows
    return out


def count_all(base):
    """返回 (创建点, 循环表行数, 逐文件明细)

    创建点 = 源码里 QPushButton(...) 这类语句的条数。
    循环表行数 = `for ... in self.ACTIONS:` 这种表的数据行数 ——
                 1 处创建点会产出 N 个控件，只数创建点会严重低估。
    """
    per, tables, total_tables = {}, {}, 0
    gui = os.path.join(base, "gui")
    if not os.path.isdir(gui):
        return per, tables, 0
    for root, dirs, fs in os.walk(gui):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(fs):
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, base).replace("\\", "/")
            try:
                src = open(p, encoding="utf-8", errors="ignore").read()
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
            n = sum(len(re.findall(r"\b%s\s*\(" % b, src)) for b in BTN)
            if n:
                per[rel] = n
            t = count_tables(src)
            if t:
                tables[rel] = t
                total_tables += sum(t.values())
    return per, tables, total_tables


def main():
    ap = argparse.ArgumentParser(description="按钮预算检查")
    ap.add_argument("--rebase", action="store_true",
                    help="把当前数量写成新基线（撤完按钮后下调用）")
    args = ap.parse_args()

    try:
        b = json.load(open(BUDGET, encoding="utf-8"))
    except Exception as e:
        print("[X] 读不到预算文件 %s: %s" % (BUDGET, e))
        print("    先跑一次 --rebase 生成基线")
        return 1

    per, tables, total_tables = count_all(BASE)
    total = sum(per.values())
    b_total = int(b.get("total", 0))
    b_per = b.get("per_file", {}) or {}
    b_tables = int(b.get("table_rows", 0))
    widgets = total + total_tables

    print("=" * 72)
    print("按钮预算检查（棘轮：只许降不许升）")
    print("=" * 72)
    print("  口径：创建点（源码里的 QPushButton(...) 语句）")
    print("        + 循环表行数（for ... in self.ACTIONS 这类，1 处创建点产出 N 个控件）")
    print()

    if args.rebase:
        b["total"] = total
        b["per_file"] = per
        b["table_rows"] = total_tables
        b["tables"] = tables
        b["_widgets"] = widgets
        json.dump(b, open(BUDGET, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  基线已更新: 创建点 %d + 表行 %d = 估算控件 %d"
              % (total, total_tables, widgets))
        return 0

    diff = total - b_total
    tdiff = total_tables - b_tables
    print("  创建点   %d / %d  %s" % (total, b_total, "✅" if diff <= 0 else "❌ 超 %d" % diff))
    print("  表行数   %d / %d  %s" % (total_tables, b_tables,
                                     "✅" if tdiff <= 0 else "❌ 超 %d" % tdiff))
    print("  估算控件 %d（基线 %d）" % (widgets, b_total + b_tables))
    print()

    over = []
    for p, n in sorted(per.items(), key=lambda kv: -kv[1]):
        cap = b_per.get(p)
        if cap is None:
            over.append("%s 新增 %d 处创建点（预算里没有这个文件）" % (p, n))
            print("  %-42s %3d /   -  ❌ 新增" % (p, n))
        elif n > cap:
            over.append("%s 超 %d 处（%d -> %d）" % (p, n - cap, cap, n))
            print("  %-42s %3d / %3d  ❌ 超 %d" % (p, n, cap, n - cap))
    for p, t in sorted(tables.items()):
        rows = sum(t.values())
        print("  %-42s 表 %s（%d 行）" % (p, "、".join(t), rows))

    print("=" * 72)
    if over or diff > 0 or tdiff > 0:
        print("超预算：")
        for o in over:
            print("   · %s" % o)
        if diff > 0:
            print("   · 创建点超 %d" % diff)
        if tdiff > 0:
            print("   · 循环表行数超 %d（加按钮表也要算进去）" % tdiff)
        print()
        print("加按钮前请先说明：为什么这个功能『说一句』替代不了它？")
        print("  能用对话/命令面板到达的，就别再加按钮。")
        print("  确实该加的（需要选文件/选区域/输密码/纯界面操作），")
        print("  改完跑：py -3 tools\\check_buttons.py --rebase")
        return 1
    print("按钮预算通过 ✅  创建点 %d + 表行 %d = 估算控件 %d"
          % (total, total_tables, widgets))
    if diff < 0 or tdiff < 0:
        print("  比基线少（控件 %d 个）—— 可以把基线降下来锁定成果："
              % (-(diff + tdiff)))
        print("      py -3 tools\\check_buttons.py --rebase")
    return 0


if __name__ == "__main__":
    from _console import use_utf8_console
    use_utf8_console()
    sys.exit(main())
