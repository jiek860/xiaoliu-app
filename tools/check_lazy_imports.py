# -*- coding: utf-8 -*-
"""检查所有懒加载模块能否编译并导入。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.lazy_health import compile_lazy_sources, isolated_check, format_report  # noqa: E402


def main():
    c = compile_lazy_sources(BASE)
    p = isolated_check(BASE)
    print(json.dumps({
        "compile": c,
        "import": {"ok": p.get("ok"), "checked": p.get("checked", 0),
                   "error": p.get("error", ""),
                   "failed": [x for x in (p.get("results") or [])
                              if not x.get("ok")]},
    }, ensure_ascii=False, indent=2))
    if not c.get("ok") or not p.get("ok"):
        print(format_report(p), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
