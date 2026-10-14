# -*- coding: utf-8 -*-
"""把开发目录同步到"打包源"目录（E:\\xiao6-package）

为什么要有这个脚本
------------------
打包流程是：开发目录 -> 复制一份干净的 -> 对那份打包。
"复制一份干净的"这一步**每次改完代码都要重做**，
靠人记得不靠谱 —— 忘了同步就会把旧代码打进安装包，
而且**装出来照样能跑**，只是行为是旧的，很难发现。

用法
----
    py -3 tools\\sync_package.py            同步（会先显示要改什么）
    py -3 tools\\sync_package.py --dry-run  只看差异，不动文件
    py -3 tools\\sync_package.py --to D:\\x  同步到别的目录

安全底线（每次同步都会检查，不通过就中止）
------------------------------------------
    · 绝不复制 data\\ backups\\ optional_libs\\ tests\\ tools\\ .git\\
    · config.default.json 里不许有填好的 Key
    · 同步后打印文件数/体积，方便和上次对比
"""
import argparse
import hashlib
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DST = r"E:\xiao6-package"

# 要同步的根级文件
FILES = ["run.py", "app.ico", "config.default.json",
         "requirements.txt", "requirements-optional.txt",
         "启动PyQt.bat", "使用说明-小白版.txt"]
# 可选：有就同步
# ⚠️ 这里**故意不放 CHANGELOG.md / docs/** —— 那是开发文档，
#    用户不需要。安装包越小越好（每多一个文件，用户就多一分困惑）。
OPTIONAL_FILES = []

# 要同步的目录
DIRS = ["core", "gui", "modules", "modules_repo", "libs"]

# 复制时排除的目录名
SKIP = {"__pycache__", "retired", ".git", ".githooks", ".pytest_cache",
        ".ruff_cache", "backup_"}

# 绝对不能出现在打包源里的
FORBIDDEN = ["data", "backups", "optional_libs", "tests", "tools",
             "scripts", "staging", ".git", ".githooks", "dist", "build",
             "logs", "docs"]


def md5(p):
    try:
        with open(p, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def walk(base):
    """列出文件 -> 哈希（相对路径用 / 分隔）"""
    out = {}
    if not os.path.isdir(base):
        return out
    for r, ds, fs in os.walk(base):
        ds[:] = [d for d in ds
                 if d not in SKIP and not d.startswith("backup_")]
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, base).replace("\\", "/")] = md5(p)
    return out


def plan(dst):
    """算出要做什么：新增 / 更新 / 删除"""
    add, upd, dele = [], [], []

    for name in FILES + [f for f in OPTIONAL_FILES
                         if os.path.exists(os.path.join(BASE, f))]:
        s, d = os.path.join(BASE, name), os.path.join(dst, name)
        if not os.path.exists(d):
            add.append(name)
        elif md5(s) != md5(d):
            upd.append(name)

    for name in DIRS:
        sm = walk(os.path.join(BASE, name))
        dm = walk(os.path.join(dst, name))
        for k in sorted(set(sm) - set(dm)):
            add.append("%s/%s" % (name, k))
        for k in sorted(set(dm) - set(sm)):
            dele.append("%s/%s" % (name, k))
        for k in sorted(set(sm) & set(dm)):
            if sm[k] != dm[k]:
                upd.append("%s/%s" % (name, k))
    return add, upd, dele


def check_safety(dst):
    """同步后检查：不该有的有没有混进来"""
    bad = [n for n in FORBIDDEN if os.path.exists(os.path.join(dst, n))]
    if bad:
        return ["打包源里混进了不该有的东西: %s" % bad]
    problems = []
    cfg = os.path.join(dst, "config.default.json")
    if os.path.exists(cfg):
        import re
        s = open(cfg, encoding="utf-8", errors="ignore").read()
        for k, v in re.findall(
                r'"(cloud_key|email_pass|webhook|api_key)"\s*:\s*"([^"]*)"',
                s, re.I):
            if v.strip():
                problems.append("config.default.json 里 %s 有值！" % k)
    return problems


def du(p):
    n = s = 0
    for r, ds, fs in os.walk(p):
        ds[:] = [d for d in ds if d not in SKIP]
        for f in fs:
            try:
                s += os.path.getsize(os.path.join(r, f))
                n += 1
            # 静默是故意的：统计体积时遇到读不到的单个文件（权限/被占用），
            # 跳过它继续数就行 —— 少算一个不影响"大概多大"这个用途
            except Exception:
                pass
    return n, s


def main():
    ap = argparse.ArgumentParser(description="同步打包源目录")
    ap.add_argument("--to", default=DEFAULT_DST, help="目标目录")
    ap.add_argument("--dry-run", action="store_true", help="只看差异")
    a = ap.parse_args()
    dst = a.to

    print("=" * 78)
    print("同步打包源：%s  ->  %s" % (BASE, dst))
    print("=" * 78)

    if not os.path.isdir(dst):
        print("  目标不存在，先建:", dst)
        if not a.dry_run:
            os.makedirs(dst, exist_ok=True)

    add, upd, dele = plan(dst)
    print("  要新增 %d 个 / 要更新 %d 个 / 要删除 %d 个"
          % (len(add), len(upd), len(dele)))
    for tag, arr in (("新增", add), ("更新", upd), ("删除", dele)):
        for k in arr[:8]:
            print("    %s %s" % (tag, k))
        if len(arr) > 8:
            print("    ... %s 还有 %d 个" % (tag, len(arr) - 8))

    if not (add or upd or dele):
        print()
        print("  ✅ 已经一致，不用动")
        return 0

    if a.dry_run:
        print()
        print("  （--dry-run，没有改动任何文件）")
        return 0

    # ── 真的同步 ──
    print()
    print("  开始同步…")
    for name in FILES + [f for f in OPTIONAL_FILES
                         if os.path.exists(os.path.join(BASE, f))]:
        s = os.path.join(BASE, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dst, name))
    for name in DIRS:
        s = os.path.join(BASE, name)
        if not os.path.isdir(s):
            continue
        shutil.copytree(s, os.path.join(dst, name),
                        ignore=shutil.ignore_patterns(*SKIP),
                        dirs_exist_ok=True)
    # 删掉源里已经没有的（保持一致）
    for k in dele:
        try:
            os.remove(os.path.join(dst, k.replace("/", os.sep)))
        # 静默是故意的：删一个源里已经没有的文件失败（被占用/只读），
        # 不该中断整次同步 —— 后面的一致性校验会把残留报出来
        except Exception:
            pass
    # 清掉可能产生的 __pycache__
    for r, ds, _fs in os.walk(dst):
        for d in list(ds):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(r, d), ignore_errors=True)

    # ── 校验 ──
    print()
    print("=" * 78)
    print("同步后校验")
    print("=" * 78)
    add2, upd2, dele2 = plan(dst)
    if add2 or upd2 or dele2:
        print("  ⚠️ 还有差异: 新增%d 更新%d 删除%d"
              % (len(add2), len(upd2), len(dele2)))
    else:
        print("  ✅ 已完全一致")

    problems = check_safety(dst)
    if problems:
        print()
        for p in problems:
            print("  ❌ %s" % p)
        return 1
    print("  ✅ 安全检查通过（没有 data/ tests/ tools/，配置里没有 Key）")

    n, s = du(dst)
    print()
    print("  %s" % dst)
    print("  %d 个文件，%.1f MB" % (n, s / 1048576))
    print()
    print("  下一步：")
    print("    1. 加固打包.exe  -> 选 %s\\run.py 编译成 exe" % dst)
    print("    2. 安装包生成器.exe -> 第⑤项选 %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
