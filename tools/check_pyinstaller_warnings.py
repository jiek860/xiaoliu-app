# -*- coding: utf-8 -*-
"""分类检查 PyInstaller missing-module warnings。

目的不是把警告全部藏起来，而是把已确认的 Unix-only、Python2 兼容、
可选依赖和 numpy 反射噪声分类；出现**未分类**模块时失败，提醒人工
判断它是不是运行必需依赖。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ALLOWLIST = BASE / "tools" / "pyinstaller_warning_allowlist.json"


def extract_missing(warn_text):
    names = []
    for line in str(warn_text or "").splitlines():
        m = re.search(r"missing module named '?([^' ]+)", line)
        if m:
            names.append(m.group(1))
    return sorted(set(names))


def load_allowlist(path=ALLOWLIST):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def classify(names, allow=None):
    allow = allow or load_allowlist()
    prefixes = allow.get("prefixes") or {}
    exact = allow.get("exact") or {}
    categories = {cat: [] for cat in exact}
    unknown = []
    for name in names:
        hit = None
        for cat, pref_list in prefixes.items():
            if any(name.startswith(p) for p in pref_list):
                hit = cat
                break
        if hit is None:
            for cat, values in exact.items():
                if name in values:
                    hit = cat
                    break
        if hit is None:
            unknown.append(name)
        else:
            categories.setdefault(hit, []).append(name)
    return categories, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn", default="build/xiao6/warn-xiao6.txt")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = Path(a.warn)
    if not p.exists():
        print("[X] 找不到 warning 文件: %s" % p)
        return 1
    names = extract_missing(p.read_text(encoding="utf-8", errors="ignore"))
    categories, unknown = classify(names)
    report = {
        "total_unique_missing": len(names),
        "categories": {k: len(v) for k, v in categories.items()},
        "unknown": unknown,
    }
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("PyInstaller missing-module 分类")
        print("  unique:", len(names))
        for k, v in sorted(categories.items()):
            if v:
                print("  %-28s %d" % (k + ":", len(v)))
        if unknown:
            print("[X] 未分类模块（必须人工判断）:")
            for n in unknown:
                print("   ", n)
        else:
            print("[OK] 所有 missing-module 均已分类")
    return 1 if unknown else 0


if __name__ == "__main__":
    raise SystemExit(main())