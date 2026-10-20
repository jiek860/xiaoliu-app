# -*- coding: utf-8 -*-
"""本地运行环境兼容性检查。"""
from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys

SUPPORTED_PYTHON = {(3, 10), (3, 11), (3, 12)}
WINDOWS_MIN_BUILD = 10240          # Windows 10 首个正式版
REQUIRED = ("PyQt5", "requests", "numpy", "cryptography", "psutil")


def classify_windows(major, build, product_type):
    """把 Windows 版本分成 10/11、旧客户端和 Server。

    Windows 7/8 也是 product_type=1 的客户端，不能因为不是 Server
    就误判成 Windows 10；用 build >= 10240 作为主支持边界。
    """
    client = int(product_type) == 1
    supported = bool(client and int(build) >= WINDOWS_MIN_BUILD)
    if not client:
        release = "server"
    elif int(build) >= 22000:
        release = "11"
    elif int(build) >= WINDOWS_MIN_BUILD:
        release = "10"
    else:
        release = "unsupported"
    return {"windows": True, "client": client,
            "supported": supported, "server": not client,
            "major": int(major), "build": int(build),
            "release": release, "product_type": int(product_type)}


def windows_version():
    if not sys.platform.startswith("win"):
        return {"windows": False, "client": False, "server": False,
                "supported": False, "build": 0,
                "release": platform.release()}
    try:
        v = sys.getwindowsversion()
        return classify_windows(v.major, v.build, v.product_type)
    except Exception as e:
        return {"windows": True, "client": False, "server": False,
                "supported": False, "build": 0,
                "release": platform.release(), "error": str(e)}


def probe():
    py = sys.version_info[:2]
    win = windows_version()
    missing = []
    for name in REQUIRED:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return {
        "python": platform.python_version(),
        "python_supported": py in SUPPORTED_PYTHON,
        "python_supported_range": "3.10-3.12",
        "platform": platform.platform(),
        "windows": win,
        "missing_required": missing,
        "ok": bool(py in SUPPORTED_PYTHON and win.get("supported")
                   and not missing),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-server", action="store_true")
    a = ap.parse_args()
    r = probe()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("Python:", r["python"], "支持" if r["python_supported"] else "不支持")
        print("平台:", r["platform"])
        print("Windows:", r["windows"])
        print("缺失依赖:", r["missing_required"] or "无")
    if not r["windows"]["windows"]:
        print("[X] 当前不是 Windows，桌面控制能力不可用", file=sys.stderr)
        return 1
    if not r["python_supported"]:
        print("[X] Python 版本不在 3.10-3.12 支持范围", file=sys.stderr)
        return 1
    if r["missing_required"]:
        print("[X] 缺少必需依赖", file=sys.stderr)
        return 1
    if r["windows"].get("client") and not r["windows"].get("supported"):
        print("[X] 当前 Windows 版本低于 Windows 10，不在主支持范围",
              file=sys.stderr)
        return 1
    if r["windows"].get("server") and not a.allow_server:
        print("[!] 当前是 Windows Server，可运行但不等于 Windows 10/11 客户端验证",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
