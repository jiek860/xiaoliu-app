# -*- coding: utf-8 -*-
"""生成便携版压缩包（Windows 主路径；Linux/macOS 作为实验路径）。"""
import argparse
import os
import platform
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE_FILES = [
    "run.py", "run_server.py", "config.default.json",
    "requirements.txt", "requirements-optional.txt",
    "README.md", "使用说明-小白版.txt", "隐私政策.txt", "用户协议.txt",
    "app.ico",
]
INCLUDE_DIRS = ["core", "gui", "modules", "modules_repo"]
OPTIONAL_DIRS = ["libs", "optional_libs"]
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache",
                "backups", "build", "dist", "data", "updates", "staging"}


def add_tree(z, root, rel):
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d not in EXCLUDE_DIRS]
        for f in fs:
            p = os.path.join(r, f)
            z.write(p, os.path.join(rel, os.path.relpath(p, root)))


def default_name():
    tag = platform.system().lower() + "-" + platform.machine().lower()
    return "xiao6-portable-%s-%s.zip" % (time.strftime("%Y%m%d"), tag)


def _resolve_out(out):
    """把 --out 解析成绝对文件路径。

    支持三种写法：
        --out portable.zip            当前目录
        --out build/portable.zip     相对目录
        --out build/                 已存在的目录
    """
    if not out:
        out = os.path.join(BASE, "build", default_name())
    out = os.path.abspath(os.path.expanduser(str(out)))
    if out.endswith(os.sep) or (os.path.isdir(out) and not out.lower().endswith(".zip")):
        out = os.path.join(out, default_name())
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return out


def build_zip(out=None, with_libs=False):
    """生成便携包，返回绝对路径。可被测试直接调用。"""
    out = _resolve_out(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in INCLUDE_FILES:
            p = os.path.join(BASE, f)
            if os.path.isfile(p):
                z.write(p, f)
        for d in INCLUDE_DIRS:
            p = os.path.join(BASE, d)
            if os.path.isdir(p):
                add_tree(z, p, d)
        if with_libs:
            for d in OPTIONAL_DIRS:
                p = os.path.join(BASE, d)
                if os.path.isdir(p):
                    add_tree(z, p, d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--with-libs", action="store_true")
    a = ap.parse_args()
    out = build_zip(a.out, with_libs=a.with_libs)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
