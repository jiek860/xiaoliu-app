# -*- coding: utf-8 -*-
"""插件安全校验（小6插件标准 v2.1 S3/S5/S6/S7/N5/N13/N15）。

用法：
    py -3 tools/check_plugin_security.py                    # 全部模块基础检查
    py -3 tools/check_plugin_security.py --level L3         # 只查 L3 插件
    py -3 tools/check_plugin_security.py --config           # 敏感配置声明检查
    py -3 tools/check_plugin_security.py --paths            # 路径越界检查
    py -3 tools/check_plugin_security.py --secrets          # 硬编码密钥检查
    py -3 tools/check_plugin_security.py --audit            # 审计日志格式检查
    py -3 tools/check_plugin_security.py --json

默认不带开关时跑 --config --paths --secrets。
"""
from __future__ import annotations

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")
SRC_DIR = os.path.join(BASE, "modules_repo")

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_PATH_ESCAPE = (
    re.compile(r"open\(\s*[\"'][/\\]"),
    re.compile(r"os\.path\.join\(\s*[\"']\.\.[\"']"),
    re.compile(r"\.\./\.\./"),
)


def _load():
    with open(MANIFEST, encoding="utf-8-sig") as f:
        return json.load(f)


def _src(meta):
    path = os.path.join(SRC_DIR, meta.get("file") or "")
    if not os.path.isfile(path):
        return None
    return open(path, encoding="utf-8", errors="replace").read()


def check_config(modules, errors, warnings):
    for meta in modules:
        name = meta.get("name")
        caps = (meta.get("capabilities") or {}).get("config") or {}
        if caps.get("read_secrets"):
            if not caps.get("secret_names"):
                errors.append("%s: read_secrets=true 但未列 secret_names（S3）"
                              % name)
        src = _src(meta) or ""
        uses_secret = "get_secret(" in src
        if uses_secret and not caps.get("read_secrets"):
            errors.append("%s: 调用了 get_secret 但未声明 read_secrets（S3/S7）"
                          % name)
        for key in caps.get("public_keys") or []:
            if re.search(r"(api[_-]?key|token|secret|password|credential|private)",
                         str(key), re.I):
                errors.append("%s: public_keys 含敏感键名 %r（S3）" % (name, key))


def check_paths(modules, errors, warnings):
    for meta in modules:
        name = meta.get("name")
        caps = (meta.get("capabilities") or {}).get("filesystem") or {}
        root = "data/plugin_data/%s" % name
        for action in ("read", "write"):
            for path in caps.get(action) or []:
                p = str(path).replace("\\", "/")
                if not (p == root or p.startswith(root + "/")):
                    errors.append("%s: filesystem.%s 越界 %r（S3/S6）"
                                  % (name, action, path))
        src = _src(meta) or ""
        for rx in _PATH_ESCAPE:
            if rx.search(src):
                warnings.append("%s: 源码出现可疑绝对/越界路径写法（S6）" % name)
                break


def check_secrets(modules, errors, warnings):
    for meta in modules:
        src = _src(meta) or ""
        for rx in _SECRET_PATTERNS:
            if rx.search(src):
                errors.append("%s: 疑似硬编码凭据（N5.3）" % meta.get("name"))
                break


def check_level(modules, errors, warnings, level):
    from core.plugin_tier import derive_tier
    for meta in modules:
        name = meta.get("name")
        caps = meta.get("capabilities") or {}
        tier = derive_tier(caps)
        if level == "L3":
            if tier != "L3":
                continue
            proc = caps.get("process") or {}
            if proc.get("enabled") and not proc.get("allow_argv"):
                errors.append("%s: L3 process.enabled 但未给固定 allow_argv（S3）"
                              % name)
            src = _src(meta) or ""
            # 清理方法可能来自基类（BaseModule 自带 close/stop），
            # 只看本文件会误报，所以同时检查是否继承 BaseModule/LifecycleMixin。
            inherited = ("from modules.base import" in src
                         or "LifecycleMixin" in src
                         or "BaseModule" in src)
            if (not inherited and "def close" not in src
                    and "def stop" not in src):
                warnings.append("%s: L3 插件建议实现 close()/stop()（N4.2）" % name)


def check_audit(errors, warnings):
    try:
        from core.plugin_audit import PluginAudit
        report = PluginAudit(BASE).validate_schema()
    except Exception as e:
        warnings.append("审计格式检查跳过: %s" % str(e)[:80])
        return
    if not report.get("ok"):
        errors.append("审计日志存在缺字段记录: %s" % report.get("missing")[:2])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    level = ""
    if "--level" in argv:
        i = argv.index("--level")
        if i + 1 < len(argv):
            level = argv[i + 1].upper()
    switches = {f for f in ("--config", "--paths", "--secrets", "--audit")
                if f in argv}
    if not switches and not level:
        switches = {"--config", "--paths", "--secrets"}

    modules = _load()
    if level in ("L2", "L3"):
        from core.plugin_tier import derive_tier
        modules = [m for m in modules
                   if derive_tier(m.get("capabilities")) == level]
    errors, warnings = [], []
    if "--config" in switches:
        check_config(modules, errors, warnings)
    if "--paths" in switches:
        check_paths(modules, errors, warnings)
    if "--secrets" in switches:
        check_secrets(modules, errors, warnings)
    if "--audit" in switches:
        check_audit(errors, warnings)
    if level:
        check_level(modules, errors, warnings, level)

    report = {"checked": len(modules), "level": level or "all",
              "errors": errors[:50], "warnings": warnings[:50],
              "ok": not errors}
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("插件安全检查（v2.1 S3/S5/S6/S7/N5/N13/N15）")
        print("=" * 70)
        print("模块 %d · level %s · error %d · warn %d"
              % (len(modules), level or "all", len(errors), len(warnings)))
        for e in errors[:20]:
            print("  [E] " + e)
        for w in warnings[:10]:
            print("  [W] " + w)
        print()
        print("[OK] 安全检查通过" if not errors else "[X] 安全检查未通过")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
