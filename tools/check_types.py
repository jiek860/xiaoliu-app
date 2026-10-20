# -*- coding: utf-8 -*-
"""本地静态质量检查：ruff + mypy。"""
import subprocess
import sys


def main():
    cmds = [
        [sys.executable, "-m", "ruff", "check", "core", "gui", "modules/installed"],
        [sys.executable, "-m", "mypy"],
    ]
    for cmd in cmds:
        print(">>> " + " ".join(cmd))
        code = subprocess.call(cmd)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
