# -*- coding: utf-8 -*-
"""版本号一致性检查 —— 防止"发版只改了 CHANGELOG、忘了改 version.py"再次发生

背景：这个项目长期有两套版本号对不上
    CHANGELOG.md 最新条目  v25.1.5
    core/version.py        v25.1.3   ← 落后两个版本，用户端版本比较会错乱
    core/__init__.py       "2.0.0"   ← 第三套，跟程序版本毫无关系
分发说明里还写着 v25.1.6（一个代码里根本不存在的版本）。

本脚本以 core/version.py 为**唯一权威**，逐个核对其它位置，
不一致就列出来并返回非零退出码，可以直接挂进发版流程/自检。

用法:
    py -3 tools\\check_version.py          # 只检查
    py -3 tools\\check_version.py --fix    # 能自动改的自动改（CHANGELOG 条目除外）
"""
import argparse
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)


def main():
    ap = argparse.ArgumentParser(description="检查版本号是否全项目一致")
    ap.add_argument("--fix", action="store_true", help="能自动改的自动改")
    args = ap.parse_args()

    try:
        from core.version import __version__ as ver
    except Exception as e:
        print("[X] 读不到 core/version.py: %s" % e)
        return 1
    ver = str(ver).strip()
    bare = ver.lstrip("vV")

    print("=" * 74)
    print("版本号一致性检查（权威来源: core/version.py = %s）" % ver)
    print("=" * 74)

    problems = []

    # ---------- 1. core/__init__.py 必须引用 version.py，不能自己写死 ----------
    p = os.path.join(BASE, "core", "__init__.py")
    if os.path.exists(p):
        src = open(p, encoding="utf-8").read()
        if re.search(r'^__version__\s*=\s*["\']', src, re.M):
            problems.append(("core/__init__.py",
                             "自己写死了一个 __version__，应改为 from .version import __version__"))
        elif "from .version import __version__" in src:
            print("  ✅ core/__init__.py 引用 core/version.py（单一来源）")
        else:
            print("  ⚠️  core/__init__.py 没有版本号字段（可选）")

    # ---------- 2. CHANGELOG 最新条目 = 当前版本 ----------
    p = os.path.join(BASE, "CHANGELOG.md")
    if os.path.exists(p):
        src = open(p, encoding="utf-8").read()
        m = re.search(r"^##\s*(v?[\d.]+)", src, re.M)
        latest = m.group(1) if m else "(找不到)"
        if latest.lstrip("vV") == bare:
            print("  ✅ CHANGELOG.md 最新条目 = %s" % latest)
        else:
            problems.append(("CHANGELOG.md",
                             "最新条目是 %s，应为 %s —— 需要在文件开头加一条 "
                             "## %s" % (latest, ver, ver)))

    # ---------- 3. 分发说明文档 ----------
    for name in ("小6智能体最新架构与功能说明.txt",):
        p = os.path.join(BASE, name)
        if not os.path.exists(p):
            continue
        src = open(p, encoding="utf-8").read()
        found = sorted(set(re.findall(r"v?25\.\d+\.\d+", src)))
        bad = [f for f in found if f.lstrip("vV") != bare]
        if bad:
            problems.append((name, "里面写着 %s，应为 %s" % ("、".join(bad), ver)))
            if args.fix:
                for b in bad:
                    src = src.replace(b, ver)
                open(p, "w", encoding="utf-8").write(src)
                print("  🔧 已把 %s 里的 %s 改成 %s" % (name, "、".join(bad), ver))
        else:
            print("  ✅ %s 版本号一致" % name)

    # ---------- 4. 扫全项目残留的旧版本号 ----------
    print()
    print("  全项目扫描其它 25.x.x 残留：")
    SKIP = ("\\libs\\", "\\optional_libs\\", "\\backups\\", "\\.git\\", "_trash",
            "\\__pycache__\\", "\\data\\", "\\modules_repo\\")
    # 这些文件里的版本号是**说明性**的，不是版本声明 —— 扫出来只会是噪声：
    #   CHANGELOG.md              历史条目（v25.1.5 等就是该留着）
    #   开发流程与目录结构梳理.md   历史提交信息示例
    #   开发者须知-密钥与发版.md    讲"版本号曾漂移"时必然要举例
    #   部署步骤.md                命令行示例
    EXPLANATORY = ("CHANGELOG.md", "开发流程与目录结构梳理.md",
                   "开发者须知-密钥与发版.md", "部署步骤.md")
    rest = []
    for root, dirs, fs in os.walk(BASE):
        dirs[:] = [d for d in dirs if d not in
                   ("__pycache__", "libs", "optional_libs", ".git", "backups",
                    "staging", "dist", "build", "data", "modules_repo")]
        for f in fs:
            if not f.lower().endswith((".py", ".md", ".txt", ".bat", ".json")):
                continue
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, BASE)
            if any(s in fp for s in SKIP) or f in EXPLANATORY:
                continue
            try:
                for i, line in enumerate(open(fp, encoding="utf-8", errors="ignore"), 1):
                    # (?<![\d.]) 避免把 "2025.4.25"（MCP SDK 版本）这类截成 "25.4.25"
                    for v in re.findall(r"(?<![\d.])v?25\.\d+\.\d+", line):
                        if v.lstrip("vV") != bare:
                            rest.append("%s:%d  %s" % (rel, i, line.strip()[:60]))
            except Exception:
                pass
    if rest:
        print("    发现 %d 处（历史记录类可忽略）:" % len(rest))
        for r in rest[:14]:
            print("      " + r)
    else:
        print("    没有残留 ✅")

    # ---------- 汇总 ----------
    print()
    print("=" * 74)
    if problems and not args.fix:
        print("发现 %d 处不一致：" % len(problems))
        for f, why in problems:
            print("   · %-34s %s" % (f, why))
        print()
        print("加 --fix 可自动修（CHANGELOG 条目需手工加）")
        return 1
    print("版本号检查通过 ✅  当前版本 %s" % ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
