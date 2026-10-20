# -*- coding: utf-8 -*-
"""运行 Agent 端到端回归集。"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    cmd = [sys.executable, "-m", "pytest", "-q",
           "tests/test_agent_e2e.py", "tests/test_agent_closure.py"]
    print(">>> " + " ".join(cmd))
    return subprocess.call(cmd, cwd=BASE)


if __name__ == "__main__":
    raise SystemExit(main())
