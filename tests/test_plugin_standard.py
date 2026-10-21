# -*- coding: utf-8 -*-
"""插件标准（capabilities / API 边界 / 清单必填项）的契约测试。

这份测试的定位：把"插件标准"从散落在代码里的规则，钉成可执行的契约。
任何一条标准被放宽或误改，这里都会红。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_api import (  # noqa: E402
    PLUGIN_API_VERSION, SUPPORTED_PLUGIN_API, validate_plugin_manifest,
    validate_plugin_source,
)
from core.plugin_capabilities import (  # noqa: E402
    CAPABILITY_KEYS, CAPABILITY_SCHEMA_VERSION, validate_capabilities,
)

MANIFEST = os.path.join(BASE, "modules_repo", "manifest.json")

# 标准要求每个条目都必须有的字段
REQUIRED_FIELDS = ("name", "title", "file", "cls", "desc", "group",
                   "version", "api_version", "first_party", "sha256",
                   "signature", "capabilities")


def _manifest():
    return json.load(open(MANIFEST, encoding="utf-8-sig"))


def test_api_version_is_declared_and_supported():
    assert PLUGIN_API_VERSION == "1.0"
    assert "1.0" in SUPPORTED_PLUGIN_API


def test_every_official_plugin_declares_all_required_fields():
    missing = []
    for meta in _manifest():
        for key in REQUIRED_FIELDS:
            if key not in meta:
                missing.append("%s 缺 %s" % (meta.get("name"), key))
    assert not missing, "插件清单不符合标准:\n  " + "\n  ".join(missing[:10])


def test_every_official_plugin_declares_capabilities():
    """不能有 legacy（未声明能力）的官方模块。"""
    legacy = [m["name"] for m in _manifest()
              if not m.get("capabilities")]
    assert not legacy, "这些官方插件没声明 capabilities: %s" % legacy


def test_capability_sections_are_complete():
    for meta in _manifest():
        caps = meta["capabilities"]
        for key in CAPABILITY_KEYS:
            assert key in caps, "%s 的 capabilities 缺 %s" % (meta["name"], key)


def test_every_manifest_entry_passes_validation_with_source():
    bad = []
    for meta in _manifest():
        path = os.path.join(BASE, "modules_repo", meta["file"])
        src = open(path, encoding="utf-8").read()
        r = validate_plugin_manifest(meta, src)
        if not r["ok"]:
            bad.append((meta["name"], r["errors"][:2]))
    assert not bad, "插件不符合标准: %s" % bad[:5]


def test_all_plugins_are_signed():
    unsigned = [m["name"] for m in _manifest()
                if not str(m.get("signature") or "").strip()]
    assert not unsigned, "未签名插件: %s" % unsigned


def test_network_capabilities_use_declared_domains_only():
    """网络能力必须带域名；为空直接算不合格。"""
    for meta in _manifest():
        net = meta["capabilities"].get("network") or {}
        if net.get("enabled"):
            assert net.get("domains"), "%s 开了网络但没写域名" % meta["name"]
            assert net.get("methods"), "%s 开了网络但没写方法" % meta["name"]


def test_high_risk_plugins_are_explicitly_declared():
    """高风险能力必须是显式声明，不能靠默认。"""
    by_name = {m["name"]: m for m in _manifest()}
    ui = by_name["computer_controller"]["capabilities"]["ui_control"]
    assert ui["enabled"] is True, "computer_controller 必须声明 ui_control"
    proc = by_name["code_runner"]["capabilities"]["process"]
    assert proc["enabled"] is True
    assert proc["allow_argv"], "code_runner 必须声明固定 argv 白名单"


def test_local_hosts_are_allowed_but_arbitrary_hosts_are_not():
    ok = validate_capabilities({"name": "x", "capabilities": {
        "network": {"enabled": True, "domains": ["localhost", "127.0.0.1"],
                    "methods": ["POST"]}}})
    assert ok["ok"] is True, ok["errors"]
    bad = validate_capabilities({"name": "x", "capabilities": {
        "network": {"enabled": True, "domains": ["http://evil.local:8080"],
                    "methods": ["GET"]}}})
    assert bad["ok"] is False


def test_third_party_cannot_import_private_core():
    r = validate_plugin_source("from core.trunk import Trunk\n", strict=True)
    assert r["ok"] is False
    r2 = validate_plugin_source("from core.secret_store import decrypt_config\n",
                                strict=True)
    assert r2["ok"] is False


def test_third_party_cannot_import_unlisted_core_module():
    r = validate_plugin_source("import core.some_internal_mod\n", strict=True)
    assert r["ok"] is False


def test_public_core_module_is_allowed():
    r = validate_plugin_source("from core.path_safety import safe_join\n",
                               strict=True)
    assert r["ok"] is True, r["errors"]


def test_star_import_from_core_is_banned():
    r = validate_plugin_source("from core import *\n", strict=True)
    assert r["ok"] is False


def test_manifest_without_api_version_is_flagged_legacy():
    r = validate_plugin_manifest({"name": "x", "file": "x.py"})
    assert r["legacy"] is True
    assert r["capability_legacy"] is True


def test_unknown_api_version_is_rejected():
    r = validate_plugin_manifest({"name": "x", "api_version": "9.9"})
    assert r["ok"] is False


def test_capability_schema_version_is_declared():
    assert CAPABILITY_SCHEMA_VERSION == "1.0"


def test_every_capability_error_is_human_readable():
    r = validate_capabilities({"name": "x", "capabilities": {
        "network": {"enabled": True, "domains": [], "methods": []}}})
    assert not r["ok"]
    assert any("domain" in e for e in r["errors"])
