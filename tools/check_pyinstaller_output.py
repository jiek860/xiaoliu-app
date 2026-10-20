# -*- coding: utf-8 -*-
"""检查 PyInstaller 产物：exe、Qt 插件、敏感文件和可选启动冒烟。"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

FORBIDDEN_NAMES = {"config.json", "data", "tests", "tools", "backups",
                   "optional_libs", "staging", ".git"}
PRIVATE_HINTS = ("私钥",)
POLICY_EXEMPT = {"公钥.pem", "激活公钥.pem", "cacert.pem"}


def find_exe(dist):
    exes = sorted(Path(dist).rglob("*.exe"))
    if not exes:
        return None
    # 优先取主程序名
    for exe in exes:
        if exe.stem == "小6智能体":
            return exe
    return exes[0]


def validate_dist(dist):
    """返回 (ok, errors, info)。纯文件检查，方便单元测试。"""
    dist = Path(dist)
    errors, info = [], {}
    if not dist.exists():
        return False, ["产物目录不存在: " + str(dist)], info
    exe = find_exe(dist)
    if exe is None:
        return False, ["没有找到 exe"], info
    info["exe"] = str(exe)
    info["exe_mb"] = round(exe.stat().st_size / 1048576, 1)
    if exe.stat().st_size < 5 * 1024 * 1024:
        errors.append("主 exe 小于 5MB，可能打包不完整")

    files = [p for p in dist.rglob("*") if p.is_file()]
    info["files"] = len(files)
    info["mb"] = round(sum(p.stat().st_size for p in files) / 1048576, 1)

    top_names = {p.name for p in dist.iterdir()} if dist.exists() else set()
    for name in FORBIDDEN_NAMES:
        if name in top_names:
            errors.append("产物顶层包含禁止项: " + name)
    # .git 无论在哪一层都不许出现
    for gitdir in dist.rglob(".git"):
        if gitdir.is_dir():
            errors.append("产物里包含 .git 目录: " + str(gitdir))
    # 运行时生成的 data/config.json 或打包时误带的 config.json
    for cfg in dist.rglob("config.json"):
        errors.append("产物里包含 config.json: " + str(cfg))
    for p in files:
        low = p.name.lower()
        if low.endswith((".key", ".pem")) and p.name not in POLICY_EXEMPT \
                and "cacert" not in low:
            if any(h in p.name for h in PRIVATE_HINTS):
                errors.append("产物里疑似包含私钥: " + str(p))

    qt_core = list(dist.rglob("Qt5Core.dll"))
    qwindows = list(dist.rglob("qwindows.dll"))
    info["qt_core"] = len(qt_core)
    info["qwindows"] = len(qwindows)
    if not qt_core:
        errors.append("缺少 Qt5Core.dll")
    if not qwindows:
        errors.append("缺少 Qt platform 插件 qwindows.dll")
    return not errors, errors, info


def launch_smoke(exe, seconds=10):
    """启动 exe 做存活检查，并清理它首次运行生成的 data/ 等运行时目录。"""
    exe = Path(exe)
    dist = exe.parent
    def _runtime_entries(root):
        root = Path(root)
        names = set()
        if root.exists():
            for name in ("data", "backups", "docs", "config.json"):
                if (root / name).exists():
                    names.add(name)
        return names

    bases = [dist, dist / "_internal"]
    before = {str(base): _runtime_entries(base) for base in bases}
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    p = subprocess.Popen([str(exe)], cwd=str(dist), env=env,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    time.sleep(max(1, int(seconds)))
    alive = p.poll() is None
    if alive:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    # 启动冒烟会在 exe 目录生成 data/backups/docs 等，不能留在待上传产物里
    for base in bases:
        after = _runtime_entries(base)
        for name in sorted(after - before[str(base)]):
            target = base / name
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink()
            # 静默是故意的：冒烟清理失败不应掩盖 exe 是否存活的主结果
            except Exception:
                pass
    return alive, p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--launch-seconds", type=int, default=0,
                    help="大于 0 时启动 exe 并检查存活")
    a = ap.parse_args()
    ok, errors, info = validate_dist(a.dist)
    print("PyInstaller 产物检查")
    for key in ("exe", "exe_mb", "files", "mb", "qt_core", "qwindows"):
        if key in info:
            print("  %-10s %s" % (key + ":", info[key]))
    if ok and a.launch_seconds > 0:
        alive, code = launch_smoke(info["exe"], a.launch_seconds)
        print("  launch    %s (exit=%s)" % ("alive" if alive else "exited", code))
        if not alive:
            errors.append("exe 启动后 %d 秒内退出" % a.launch_seconds)
    if errors:
        print("[X] 失败:")
        for e in errors:
            print("   ", e)
        return 1
    print("[OK] 打包产物检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())