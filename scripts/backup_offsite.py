# -*- coding: utf-8 -*-
"""异盘备份（P2-9）：把程序与关键数据复制到**另一块盘**，消除同盘单点。

为什么需要
----------
原来只有项目目录里的 `backups/`（自动更新自己建的）。备份和源码在同一块盘上 ——
盘坏、误删、勒索加密，两边一起没。这个脚本把**代码 + 关键数据**同步到
另一块盘，建议每周跑一次（见 docs/97）。

目标盘怎么定
------------
默认**自动挑**：从 D: 往后找一块「可写、剩余空间 > 200 MB、且不是项目所在盘」的盘，
有 `网盘/OneDrive/坚果云…` 目录就放进其下。本机实测 D: 是 Windows 安装介质
（只读、0 空闲），所以不能写死 `D:\\网盘` —— 写死会直接 PermissionError。

用法
----
    py -3 scripts\\backup_offsite.py --dry-run        # 只算体积，不写盘
    py -3 scripts\\backup_offsite.py                  # 真复制
    py -3 scripts\\backup_offsite.py --keep 6         # 保留最近 6 份（默认 4）
    py -3 scripts\\backup_offsite.py --dest "E:\\bak"  # 换目标盘

目标目录优先取：--dest > 环境变量 X6_OFFSITE_BACKUP > data/config.json 的
「备份异盘目录」 > 自动挑选。目标与项目同盘时默认拒绝（--allow-same-drive 可强跑，仅自测）。

退出码：0 成功；1 没找到可写目标盘/复制出错；2 参数错误。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:  # 直接跑脚本时把项目根加进来，方便读版本号
    sys.path.insert(0, BASE)

# 要备份的代码目录（不含 __pycache__/.pyc）
CODE_DIRS = ("core", "gui", "modules", "modules_repo", "plugin_repo",
             "tools", "scripts", "docs", "templates", "config")
# 要备份的关键数据（大的、可再生的目录单独排除，见 DATA_EXCLUDE）
DATA_DIR = "data"
DATA_EXCLUDE = {
    "browsers",        # 718 MB 的 Chromium，可重新下载
    "logs",            # 17 MB 运行日志，排错时才要
    "datasets",        # 35 MB 训练/评测数据
    "swebench",        # 11 MB SWE-bench 环境
    "workspace_index", # 17 MB 可重建索引
    "dumps", "archive", "staging", "backups", "cache", "browser_sessions",
}
# 任意层级都跳过的名字
SKIP_NAMES = {"__pycache__", ".git", ".venv", ".mypy_cache", ".pytest_cache",
              ".ruff_cache", "node_modules", ".build-venv", ".runtime-venv",
              ".swebench-venv", "optional_libs", "libs"}
# 根目录要顺带带走的小文件（启动入口/清单/说明）
ROOT_FILES = ("run.py", "run_server.py", "build_release.py", "xiao6.spec",
              "config.default.json", "requirements.txt", "pyproject.toml",
              "CHANGELOG.md", "README.md")

DEFAULT_SUBDIR = "xiao6-backup"

# 自动挑选目标盘的候选目录名（云盘/网盘客户端常用的同步目录）
SYNC_DIR_NAMES = ("网盘", "OneDrive", "坚果云", "百度网盘", "WPS网盘")


def _config_dest():
    """从 data/config.json 读「备份异盘目录」（用户可自己配）"""
    try:
        p = os.path.join(BASE, "data", "config.json")
        with open(p, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        v = str(cfg.get("备份异盘目录") or "").strip()
        return v or ""
    except Exception:  # 静默是故意的：读不到配置就退回自动挑选
        return ""


def _drive_of(path):
    d = os.path.splitdrive(os.path.abspath(path))[0]
    return (d + os.sep) if d else os.sep


def _writable(root, min_free_mb=200):
    """这个盘能不能写（有些盘是只读 U 盘/ISO 介质，会 PermissionError）"""
    if not os.path.isdir(root):
        return False
    try:
        free = shutil.disk_usage(root).free
        if free < min_free_mb * 1048576:
            return False
        probe = os.path.join(root, ".x6_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def _auto_pick():
    """自动找一块**可写、空间够、不是项目所在盘**的盘。

    本机实测：D: 是 Windows 安装介质（只读，0 空闲），所以"写死 D:\\网盘"
    会直接 PermissionError。这里先探测再决定，找不到就明确告诉用户怎么办。
    """
    src_drive = _drive_of(BASE).upper()
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = letter + ":\\"
        if root.upper() == src_drive:
            continue
        if not os.path.isdir(root) or not _writable(root):
            continue
        for name in SYNC_DIR_NAMES:
            d = os.path.join(root, name)
            if os.path.isdir(d) and _writable(d, 50):
                return os.path.join(d, DEFAULT_SUBDIR)
        return os.path.join(root, DEFAULT_SUBDIR)
    return ""


def resolve_dest(arg=""):
    """目标目录：显式参数 > 环境变量 > config > 自动挑选"""
    return (arg or os.environ.get("X6_OFFSITE_BACKUP", "")
            or _config_dest() or _auto_pick())


def _copy_tree(src, dst, dry=False, skip_dirs=()):
    """复制一棵树，跳过 SKIP_NAMES 与指定子目录"""
    n = size = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs
                   if d not in SKIP_NAMES
                   and not (os.path.abspath(root) == os.path.abspath(src)
                            and d in skip_dirs)]
        rel = os.path.relpath(root, src)
        out_dir = dst if rel == "." else os.path.join(dst, rel)
        if not dry:
            os.makedirs(out_dir, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            s = os.path.join(root, f)
            # 文件名的中文在 GBK 控制台下会炸，这里统一交给 shutil（unicode 路径）
            t = os.path.join(out_dir, f)
            try:
                size += os.path.getsize(s)
                n += 1
                if not dry:
                    shutil.copy2(s, t)
            except OSError as e:
                print("  [跳过] %s (%s)" % (os.path.relpath(s, BASE),
                                           str(e)[:60]))
    return n, size


def _prune(dest_root, keep):
    """只留最近 keep 份 xiao6_* 快照"""
    try:
        items = [d for d in os.listdir(dest_root) if d.startswith("xiao6_")]
    except OSError:
        return []
    items.sort()
    removed = []
    while len(items) > keep:
        old = items.pop(0)
        p = os.path.join(dest_root, old)
        try:
            shutil.rmtree(p)
            removed.append(old)
        except OSError as e:
            print("  [清理失败] %s (%s)" % (old, str(e)[:60]))
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description="异盘备份（程序 + 关键数据）")
    ap.add_argument("--dest", default="",
                    help="目标目录（默认自动挑一块可写的非项目盘）")
    ap.add_argument("--keep", type=int, default=4, help="保留最近几份（默认 4）")
    ap.add_argument("--dry-run", action="store_true", help="只算体积，不写盘")
    ap.add_argument("--allow-same-drive", action="store_true",
                    help="目标与项目在同一块盘也照做（只用于自测）")
    args = ap.parse_args(argv)

    dest_root = resolve_dest(args.dest)
    print("=" * 62)
    print("异盘备份 · 源 %s" % BASE)
    print("           目标 %s" % (dest_root or "(没找到可写的第二块盘)"))
    print("=" * 62)

    if not dest_root:
        print("[X] 没有找到可写的第二块盘。三个办法：")
        print("    1) 插一块移动硬盘/U 盘，再跑本脚本（会自动挑盘）")
        print("    2) 指定网盘同步目录：--dest \"C:\\Users\\你\\OneDrive\\xiao6-backup\"")
        print("    3) 写进 data/config.json 的「备份异盘目录」，以后不用带参数")
        return 1
    if not _writable(_drive_of(dest_root)):
        print("[X] 目标 %s 不可写（只读介质/没权限/空间不足）" % dest_root)
        return 1
    if os.path.abspath(dest_root).startswith(os.path.abspath(BASE)):
        print("[X] 目标目录不能在项目目录里（那就不是异盘了）")
        return 1
    same = _drive_of(dest_root).upper() == _drive_of(BASE).upper()
    if same and not args.allow_same_drive:
        print("[X] 目标和项目在同一块盘（%s），起不到「盘坏了还有一份」的作用。"
              % _drive_of(dest_root))
        print("    换一块盘，或用 --allow-same-drive 强行跑（仅自测）")
        return 1
    if same:
        print("[!] 目标与项目同盘（仅自测可以，正式备份要换盘）")

    stamp = time.strftime("%Y%m%d_%H%M")
    snap = os.path.join(dest_root, "xiao6_%s" % stamp)
    todo = [(d, os.path.join(BASE, d), os.path.join(snap, d))
            for d in CODE_DIRS if os.path.isdir(os.path.join(BASE, d))]
    todo.append((DATA_DIR, os.path.join(BASE, DATA_DIR),
                 os.path.join(snap, DATA_DIR)))

    files = size = 0
    t0 = time.time()
    if not args.dry_run:
        os.makedirs(snap, exist_ok=True)
    for label, src, dst in todo:
        skip = DATA_EXCLUDE if label == DATA_DIR else ()
        n, b = _copy_tree(src, dst, dry=args.dry_run, skip_dirs=skip)
        files += n
        size += b
        print("  %-14s %5d 个文件 %8.1f MB" % (label, n, b / 1048576.0))

    if not args.dry_run:
        for name in ROOT_FILES:
            src = os.path.join(BASE, name)
            if os.path.isfile(src):
                try:
                    shutil.copy2(src, os.path.join(snap, name))
                    files += 1
                except OSError as e:
                    print("  [跳过] %s (%s)" % (name, str(e)[:60]))
        manifest = {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": BASE,
            "files": files,
            "bytes": size,
            "version": _read_version(),
            "note": "由 scripts/backup_offsite.py 生成；恢复了就把整个目录拷回项目位置",
        }
        with open(os.path.join(snap, "backup_manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        removed = _prune(dest_root, max(1, args.keep))
        if removed:
            print("  清理旧快照: %s" % ", ".join(removed))

    dt = time.time() - t0
    print("-" * 62)
    print("%s %d 个文件 · %.1f MB · %.1f 秒"
          % ("[预演] 将复制" if args.dry_run else "[完成] 已复制",
             files, size / 1048576.0, dt))
    if args.dry_run:
        print("预演结束，未写盘。去掉 --dry-run 真复制。")
    else:
        print("快照目录: %s" % snap)
        print("恢复：把该目录下的 core/gui/modules/data/... 拷回项目对应位置即可")
    return 0


def _read_version():
    try:
        from core.version import __version__  # type: ignore
        return str(__version__)
    except Exception:  # 静默是故意的：备份不依赖版本号能否读到
        return ""


if __name__ == "__main__":
    sys.exit(main())
