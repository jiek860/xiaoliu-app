# -*- coding: utf-8 -*-
"""列出 `except Exception: pass` 形态，供分批收敛使用。"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def scan():
    rows = []
    for root in ("core", "gui", "modules/installed"):
        for p in (BASE / root).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(src)
            # 静默是故意的：单个文件语法错误只跳过，由主清单继续扫描其余文件
            except Exception:
                continue
            lines = src.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if getattr(node.type, "id", "") != "Exception":
                    continue
                if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
                    continue
                line = lines[node.lineno - 1].strip() if node.lineno else ""
                rows.append({
                    "file": str(p.relative_to(BASE)).replace("\\", "/"),
                    "line": node.lineno,
                    "has_comment": "#" in line,
                    "source": line[:160],
                })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    rows = scan()
    if a.json:
        print(json.dumps({"count": len(rows), "items": rows[:a.limit]},
                         ensure_ascii=False, indent=2))
        return 0
    print("except Exception: pass 共 %d 处" % len(rows))
    for r in rows[:a.limit]:
        print("%-52s:%-5s %s" % (r["file"], r["line"],
                                 "有注释" if r["has_comment"] else "无注释"))
    if len(rows) > a.limit:
        print("... 还有 %d 处" % (len(rows) - a.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())