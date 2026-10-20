# -*- coding: utf-8 -*-
"""测真实代码覆盖率 —— 别拍脑袋定"要补哪些测试"

为什么要有这个工具
------------------
那份工程化方案初版写的是"覆盖率 0.24，补 11 个用例涨到 0.4"。
一核实：**0.24 是"测试行数 : 生产行数"，不是代码覆盖率。**
实测真实语句覆盖率是 **41.7%** —— 比 0.24 高得多，
而且到 40% 根本不用补（已经过了）。

**教训：补测试之前先测量。** 不测量就只能拍脑袋，
拍出来的目标既可能太低（浪费）也可能做不到（白干）。

用法
----
    py -3 tools\\measure_coverage.py              跑全量测试 + 出报告
    py -3 tools\\measure_coverage.py --quick      只跑核心测试（快，约 30 秒）
    py -3 tools\\measure_coverage.py --top 20     多看几个最差的文件
    py -3 tools\\measure_coverage.py --json out.json   同时存 json（给 CI 用）

它跑的是**真的全量测试**（不是估算），所以慢（约 2 分钟）。
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

SRC = "core,gui,modules/installed"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _py():
    return [sys.executable]


def ensure_coverage():
    r = subprocess.run(_py() + ["-m", "coverage", "--version"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True
    print("  没装 coverage，正在装（走国内源）…")
    r = subprocess.run(_py() + ["-m", "pip", "install", "coverage",
                                "-i", MIRROR, "-q"],
                       capture_output=True, text=True)
    return r.returncode == 0


def run(quick=False):
    target = "tests/test_core.py" if quick else "tests/"
    print("=" * 78)
    print("跑测试并统计覆盖率（%s）" % ("快速：只有 test_core.py"
                                        if quick else "全量"))
    print("=" * 78)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        _py() + ["-m", "coverage", "run", "--source=" + SRC,
                 "-m", "pytest", target, "-q"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, cwd=BASE, timeout=1800)
    tail = [l for l in (r.stdout or "").splitlines() if l.strip()][-2:]
    for l in tail:
        print("  " + l)
    return r.returncode == 0


def report(top=12, json_out=None, quick=False):
    jf = os.path.join(BASE, "_cov_tmp.json")
    cmd = _py() + ["-m", "coverage", "json", "-o", jf, "-q"]
    if json_out:
        cmd = _py() + ["-m", "coverage", "json", "-o", json_out, "-q"]
    subprocess.run(cmd, capture_output=True, text=True, cwd=BASE)
    if not os.path.exists(jf) and not json_out:
        print("  ❌ 没生成覆盖率数据（测试可能没跑起来）")
        return 1
    src = json_out if json_out else jf
    if not os.path.exists(src):
        print("  ❌ 找不到覆盖率数据")
        return 1
    d = json.load(open(src, encoding="utf-8"))
    if not json_out:
        os.remove(jf)

    tot = d["totals"]
    print()
    print("=" * 78)
    print("① 总览")
    print("=" * 78)
    if quick:
        print("  ⚠️ **这是 --quick 的结果，数字和排名都不能用来定计划**")
        print("     它只跑了 test_core.py（十几个用例），覆盖率会低到 6% 上下。")
        print("     它的用途是「验证工具本身跑得通」，不是「看真实覆盖率」。")
        print("     要定补测试的计划，去掉 --quick 跑全量（约 2 分钟）。")
        print()
    print("  语句 %d，未覆盖 %d" % (tot["num_statements"],
                                    tot["missing_lines"]))
    print("  **覆盖率 %.1f%%**" % tot["percent_covered"])
    print()
    print("  ⚠️ 这个数是**语句覆盖率**，不是「测试行数:生产行数」——")
    print("     那两个数完全不同，别混（方案初版就是混了，把 0.24 当成覆盖率）")

    print()
    print("=" * 78)
    print("② 分目录")
    print("=" * 78)
    by = defaultdict(lambda: [0, 0, 0])
    for p, v in d["files"].items():
        q = p.replace("\\", "/")
        k = ("core" if q.startswith("core/") else
             "gui" if q.startswith("gui/") else
             "modules/installed" if q.startswith("modules/installed/") else
             "其他")
        s = v["summary"]
        by[k][0] += s["num_statements"]
        by[k][1] += s["missing_lines"]
        by[k][2] += 1
    for k, (s, m, n) in sorted(by.items(), key=lambda x: -x[1][0]):
        cov = (s - m) / s * 100 if s else 0
        filled = int(cov / 5)
        print("  %-18s %5d 语句 %6.1f%%  %s%s  (%d 文件)"
              % (k, s, cov, "█" * filled, "·" * (20 - filled), n))

    print()
    print("=" * 78)
    print("③ 最该补的 %d 个（**语句多 × 覆盖低**，不是单纯覆盖低）" % top)
    print("=" * 78)
    rows = []
    for p, v in d["files"].items():
        s = v["summary"]
        if s["num_statements"] < 30:
            continue                     # 太小的文件补了也不值
        miss = s["missing_lines"]
        rows.append((miss, s["percent_covered"], p.replace("\\", "/"),
                     s["num_statements"]))
    rows.sort(reverse=True)
    print("  %-46s %6s %6s %6s" % ("文件", "语句", "覆盖", "缺"))
    for miss, pc, p, s in rows[:top]:
        print("  %-46s %6d %5.1f%% %6d" % (p, s, pc, miss))

    print()
    print("=" * 78)
    print("④ 覆盖最好的 8 个（这些是稳的，别动）")
    print("=" * 78)
    ok = sorted([r for r in rows if r[0] < 99999], key=lambda x: -x[1])[:8]
    for _miss, pc, p, s in ok:
        print("  %5.1f%%  %-44s %4d 语句" % (pc, p, s))

    print()
    print("=" * 78)
    print("⑤ 怎么用这份报告")
    print("=" * 78)
    print("  · **照着③去打**，别拍脑袋点模块名")
    print("  · 优先级不只看数字，还要看「错了会怎样」：")
    print("      会改用户数据的（auto_updater / backup）> 用户会主动点的")
    print("      （self_check）> 内部服务（module_server）")
    print("  · 不要为了数字补 GUI 点击细节 —— 那类手动验证更划算")
    print("  · 验收标准不是「到多少个百分点」，而是")
    print("      「每个会改用户数据的函数，都有测试证明它改对了、改坏能回滚」")
    return 0


def main():
    ap = argparse.ArgumentParser(description="测真实代码覆盖率")
    ap.add_argument("--quick", action="store_true", help="只跑核心测试")
    ap.add_argument("--top", type=int, default=12, help="列几个最该补的")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="同时存 json（CI 用）")
    a = ap.parse_args()

    if not ensure_coverage():
        print("  ❌ coverage 装不上 —— 检查网络或换源")
        return 1
    if not run(quick=a.quick):
        print()
        print("  ⚠️ 测试有失败 —— 覆盖率数据仍然可用，但先修失败")
    return report(top=a.top, json_out=a.json_out, quick=a.quick)


if __name__ == "__main__":
    sys.exit(main())
