# -*- coding: utf-8 -*-
"""可选依赖状态查询 / 登记

用法：
    py -3 tools\\optional_deps.py            看哪些功能可用、缺什么
    py -3 tools\\optional_deps.py --record   生成登记表 data/optional_deps.json
    py -3 tools\\optional_deps.py --dist     看分发时该不该带 optional_libs

为什么需要这个命令
------------------
小6 的"按需安装"其实早就做好了（requirements-optional.txt +
install_optional.bat + 设置里的功能扩展组件）。缺的是"按需**知道**"：
    · optional_libs/ 里装着 1050 MB，但没有任何地方记录装了什么、什么版本
    · 用户问"我这环境哪些功能能用"没答案
    · 分发时不知道该不该拷 optional_libs/（拷了就多 1 GB）
    · 某个可选包版本不对导致诡异报错时，没有对照依据

DSH 用 dsh-runtimes/<runtime>/runtime.json 记这些。这是它的对应物。
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (BASE, os.path.join(BASE, "libs"), os.path.join(BASE, "optional_libs")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)


def main():
    ap = argparse.ArgumentParser(description="可选依赖状态")
    ap.add_argument("--record", action="store_true", help="生成登记表")
    ap.add_argument("--dist", action="store_true", help="分发建议")
    ap.add_argument("-v", "--verbose", action="store_true", help="列出每个包")
    args = ap.parse_args()

    from core import optional_deps as od

    if args.dist:
        h = od.distribution_hint(BASE)
        print("=" * 78)
        print("分发建议")
        print("=" * 78)
        for k, v in h.items():
            print("  %s: %s" % (k, v))
        return 0

    if args.record:
        r = od.record(BASE)
        print("=" * 78)
        print("生成登记表")
        print("=" * 78)
        if r.get("ok"):
            print("  ✅ %s" % r["文件"])
            print("  %s" % r["摘要"])
            return 0
        print("  ❌ %s" % r.get("错误"))
        return 1

    s = od.scan(BASE)
    print("=" * 78)
    print("可选功能状态（核心依赖之外的部分）")
    print("=" * 78)
    for feat, v in s.items():
        mark = "✅ 可用" if v["可用"] else "❌ 缺依赖"
        locs = "、".join(sorted(set(v["位置"].values()))) or "-"
        print("  %-14s %-10s %s" % (feat, mark, locs))
        if not v["可用"]:
            print("       缺: %s" % "、".join(v["缺"]))
            print("       装: %s" % v["装法"])
        elif args.verbose:
            for p, ver in sorted(v["版本"].items()):
                print("       %-22s %s" % (p, ver or "(版本未知)"))

    print()
    print("=" * 78)
    st = od.status(BASE)
    print("  %s" % st["摘要"])
    if st["缺依赖"]:
        print()
        print("  缺依赖的功能装法（装进项目目录，不污染系统 Python）：")
        print("     scripts\\install_optional.bat")
        print("     或 py -3 -m pip install --target optional_libs "
              "-r requirements-optional.txt \\")
        print("          -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print("     ⚠️ 一定要带 -i 走国内源 —— 不带会走 PyPI 官方源，")
        print("        国内经常慢到以为卡死（PyQt5 / torch 那种大包尤其明显）。")
    print()
    print("  提示：这些包可以在新机器上重新装 —— 分发时**不必拷 optional_libs/**")
    print("        （实测可省 %s）。详见 py -3 tools\\optional_deps.py --dist"
          % od.distribution_hint(BASE).get("可省", "?"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
