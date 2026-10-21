# -*- coding: utf-8 -*-
"""插件分级与风险等级校验（小6插件标准 v2.1 §0.3 / 附录 A.4）。

用法：
    py -3 tools/check_plugin_tier.py                 # 校验全部
    py -3 tools/check_plugin_tier.py <plugin>        # 校验单个
    py -3 tools/check_plugin_tier.py --json

退出码：0 全部一致；1 有不一致或字段缺失。
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.plugin_tier import check_manifest, derive  # noqa: E402

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")


def _load():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    names = [a for a in argv if not a.startswith("-")]
    modules = _load()
    if names:
        modules = [m for m in modules if m.get("name") in names]
    rows, bad = [], 0
    for meta in modules:
        r = check_manifest(meta)
        tier, risk, why = derive(meta.get("capabilities"))
        row = {"name": meta.get("name"), "declared_tier": meta.get("plugin_tier"),
               "derived_tier": tier, "declared_risk": meta.get("risk_level"),
               "derived_risk": risk, "reasons": why,
               "ok": r["ok"] and bool(meta.get("plugin_tier"))
               and bool(meta.get("risk_level"))}
        if not row["ok"]:
            bad += 1
        rows.append(row)
    if as_json:
        print(json.dumps({"checked": len(rows), "failed": bad, "rows": rows},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("插件分级校验（v2.1 §0.3）")
        print("=" * 70)
        for r in rows:
            mark = "OK " if r["ok"] else "BAD"
            print("  [%s] %-24s tier=%-2s risk=%-6s (%s)"
                  % (mark, r["name"], r["derived_tier"], r["derived_risk"],
                     ", ".join(r["reasons"])))
        print()
        if bad:
            print("[X] %d/%d 个模块分级/风险字段缺失或不一致" % (bad, len(rows)))
            return 1
        print("[OK] %d 个模块分级与风险等级全部一致" % len(rows))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
