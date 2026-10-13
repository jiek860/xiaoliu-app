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
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUDGET = os.path.join(BASE, "tools", "button_budget.json")

BTN = ("QPushButton", "QToolButton", "QRadioButton", "QCheckBox",
       "QCommandLinkButton", "QAction")


def count_all(base):
    per = {}
    gui = os.path.join(base, "gui")
    if not os.path.isdir(gui):
        return per
    for root, dirs, fs in os.walk(gui):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(fs):
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, base).replace("\\", "/")
            try:
                src = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            n = sum(len(re.findall(r"\b%s\s*\(" % b, src)) for b in BTN)
            if n:
                per[rel] = n
    return per


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

    per = count_all(BASE)
    total = sum(per.values())
    b_total = int(b.get("total", 0))
    b_per = b.get("per_file", {}) or {}

    print("=" * 72)
    print("按钮预算检查（棘轮：只许降不许升）")
    print("=" * 72)

    if args.rebase:
        b["total"] = total
        b["per_file"] = per
        json.dump(b, open(BUDGET, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("  基线已更新: total=%d，%d 个文件" % (total, len(per)))
        return 0

    over = []
    # 总量的对比
    diff = total - b_total
    print("  合计 %d / %d  %s"
          % (total, b_total,
             "✅" if diff <= 0 else "❌ 超 %d" % diff))

    # 逐文件：只看变多的和新增的
    for p, n in sorted(per.items(), key=lambda kv: -kv[1]):
        cap = b_per.get(p)
        if cap is None:
            over.append("%s 新增 %d 个（预算里没有这个文件）" % (p, n))
            print("  %-42s %3d /   -  ❌ 新增" % (p, n))
        elif n > cap:
            over.append("%s 超 %d 个（%d -> %d）" % (p, n - cap, cap, n))
            print("  %-42s %3d / %3d  ❌ 超 %d" % (p, n, cap, n - cap))
        elif n < cap:
            print("  %-42s %3d / %3d  ✅ 减了 %d" % (p, n, cap, cap - n))

    print("=" * 72)
    if over or diff > 0:
        print("超预算 %d 项：" % len(over))
        for o in over:
            print("   · %s" % o)
        if diff > 0:
            print("   · 总量超 %d" % diff)
        print()
        print("加按钮前请先说明：为什么这个功能『说一句』替代不了它？")
        print("  能用对话/命令面板到达的，就别再加按钮。")
        print("  确实该加的（需要选文件/选区域/输密码/纯界面操作），")
        print("  改完跑：py -3 tools\\check_buttons.py --rebase")
        return 1
    print("按钮预算通过 ✅  合计 %d（基线 %d）" % (total, b_total))
    if diff < 0:
        print("  比基线少 %d 个 —— 可以把基线降下来锁定成果："
              % (-diff))
        print("      py -3 tools\\check_buttons.py --rebase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
