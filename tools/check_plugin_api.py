# -*- coding: utf-8 -*-
"""检查已安装插件是否只依赖允许的 core 公共 API。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.plugin_api import (  # noqa: E402
    PLUGIN_API_VERSION, manifest_api_version, validate_plugin_file,
)


def main():
    d = os.path.join(BASE, "modules", "installed")
    manifest_path = os.path.join(BASE, "modules_repo", "manifest.json")
    metas = {}
    manifest_errors = []
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path, encoding="utf-8-sig"))
            for m in manifest:
                if not isinstance(m, dict):
                    manifest_errors.append("清单条目不是对象")
                    continue
                mv = manifest_api_version(m)
                if not mv.get("ok"):
                    manifest_errors.append("%s: %s" % (
                        m.get("file") or m.get("name"),
                        "；".join(mv.get("errors") or [])))
                if m.get("file"):
                    metas[m["file"]] = m
        except Exception as e:
            manifest_errors.append("manifest.json 读取失败: %s" % str(e)[:120])
    else:
        manifest_errors.append("modules_repo/manifest.json 不存在")

    results, warnings = [], []
    checked = 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        checked += 1
        meta = metas.get(name) or {}
        first_party = bool(meta.get("first_party"))
        r = validate_plugin_file(
            os.path.join(d, name), strict=not first_party,
            first_party=first_party)
        warnings.extend("%s: %s" % (name, w) for w in (r.get("warnings") or []))
        if not r.get("ok"):
            results.append({"plugin": name, "errors": r.get("errors")})
    report = {
        "api_version": PLUGIN_API_VERSION,
        "checked": checked,
        "manifest_errors": manifest_errors,
        "warnings": warnings[:20],
        "failed": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not results and not manifest_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())