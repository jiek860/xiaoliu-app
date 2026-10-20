# -*- coding: utf-8 -*-
"""分层文件长度守卫。

策略：
* 普通文件目标 200-400 行；
* 核心复杂模块目标 300-450 行；
* 500 行开始警告；
* 新文件/未登记文件超过 600 行失败；
* 800 行以上进入冻结区，禁止新增代码；
* 存量超标文件按预算冻结，只许下降。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(BASE, "tools", "file_size_baseline.json")
ROOTS = ("core", "gui", "modules/installed")


def load_policy():
    with open(BASELINE, encoding="utf-8-sig") as f:
        d = json.load(f)
    return d.get("policy") or {}, d.get("per_file_budgets") or {}


def scan():
    rows = []
    for root in ROOTS:
        for dp, dn, fn in os.walk(os.path.join(BASE, root)):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for name in fn:
                if not name.endswith(".py"):
                    continue
                p = os.path.join(dp, name)
                try:
                    n = len(open(p, encoding="utf-8", errors="ignore")
                            .read().splitlines())
                except OSError:
                    continue
                rows.append((n, os.path.relpath(p, BASE).replace("\\", "/")))
    return sorted(rows, reverse=True)


def evaluate(rows, policy, budgets):
    default_max = int(policy.get("default_max_lines", 600))
    split_lines = int(policy.get("split_required_lines", 600))
    warn_lines = int(policy.get("warn_lines", 500))
    block_lines = int(policy.get("block_new_code_lines", 800))
    errors, warnings, blocked = [], [], []
    for n, rel in rows:
        spec = budgets.get(rel)
        if isinstance(spec, dict):
            cap = int(spec.get("budget", default_max))
            category = spec.get("category", "ordinary")
            status = spec.get("status", "")
        else:
            cap = int(spec or default_max)
            category = "ordinary"
            status = ""
        if spec is None and n >= split_lines:
            errors.append((n, rel, split_lines, "达到 600 行，必须拆分"))
        elif n > cap:
            errors.append((n, rel, cap, "超过冻结/登记预算"))
        if n > warn_lines:
            warnings.append((n, rel, warn_lines, "超过 500 行警告线"))
        if n > block_lines or status == "legacy_blocked":
            blocked.append((n, rel, block_lines,
                            "800 行以上冻结：禁止继续新增代码，必须拆分"))
    return errors, warnings, blocked


def main():
    policy, budgets = load_policy()
    default_max = int(policy.get("default_max_lines", 600))
    rows = scan()
    errors, warnings, blocked = evaluate(rows, policy, budgets)
    print("默认新文件上限：%d 行；警告线：%d 行；冻结线：%d 行" % (
        default_max, int(policy.get("warn_lines", 500)),
        int(policy.get("block_new_code_lines", 800))))
    print("普通目标：%s；核心复杂目标：%s；门面目标：%s" % (
        policy.get("targets", {}).get("ordinary"),
        policy.get("targets", {}).get("core_complex"),
        policy.get("targets", {}).get("facade")))
    if warnings:
        print("\n[WARN] 500 行以上文件：")
        for n, rel, _, _ in warnings:
            print("  %5d  %s" % (n, rel))
    if blocked:
        print("\n[BLOCK] 800 行以上/冻结文件：禁止新增代码，只能拆分或降行数：")
        for n, rel, _, _ in blocked:
            print("  %5d  %s" % (n, rel))
    if errors:
        print("\n[ERROR] 超过预算：")
        for n, rel, cap, why in errors:
            print("  %5d / %5d  %s  (%s)" % (n, cap, rel, why))
        return 1
    print("\n文件长度守卫通过（警告不阻塞开发，但 >600 新文件或预算上涨会失败）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
