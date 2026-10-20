# -*- coding: utf-8 -*-
"""Plugin capability manifest v2, runtime checks and PermissionCenter tests."""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_capabilities import (  # noqa: E402
    capability_allows, capability_summary, default_capabilities,
    validate_capabilities,
)


def _valid_manifest():
    return {
        "name": "demo",
        "api_version": "1.0",
        "capabilities": {
            "network": {"enabled": True,
                        "domains": ["api.example.com", "*.trusted.test"],
                        "methods": ["GET", "POST"]},
            "filesystem": {
                "read": ["data/plugin_data/demo/inbox"],
                "write": ["data/plugin_data/demo/outbox"],
            },
            "process": {"enabled": False},
            "ui_control": {"enabled": False},
            "config": {"read_secrets": False, "public_keys": ["theme"]},
        },
    }


def test_missing_capabilities_is_legacy_and_default_deny():
    r = validate_capabilities({"name": "old"})
    assert r["ok"] is True
    assert r["legacy"] is True
    assert r["capabilities"] == default_capabilities()
    assert capability_allows(r["capabilities"], "network",
                             domain="example.com", method="GET")[0] is False
    assert "legacy" in capability_summary(r)


def test_valid_manifest_normalizes_and_reports_risk():
    r = validate_capabilities(_valid_manifest())
    assert r["ok"] is True, r
    caps = r["capabilities"]
    assert caps["network"]["methods"] == ["GET", "POST"]
    assert r["risk_level"] == "medium"


def test_network_capability_enforcement():
    caps = validate_capabilities(_valid_manifest())["capabilities"]
    assert capability_allows(caps, "network", domain="api.example.com",
                             method="post")[0] is True
    assert capability_allows(caps, "network", domain="x.trusted.test",
                             method="GET")[0] is True
    assert capability_allows(caps, "network", domain="evil.test",
                             method="GET")[0] is False
    assert capability_allows(caps, "network", domain="api.example.com",
                             method="DELETE")[0] is False


def test_filesystem_scope_cannot_escape_plugin_root(tmp_path):
    caps = validate_capabilities(_valid_manifest())["capabilities"]
    root = os.path.join(tmp_path, "data", "plugin_data", "demo")
    os.makedirs(os.path.join(root, "outbox"), exist_ok=True)
    os.makedirs(os.path.join(root, "other"), exist_ok=True)
    target = os.path.join(root, "outbox", "a.txt")
    assert capability_allows(caps, "filesystem", plugin_root=root,
                             path=target, method="write")[0] is True
    assert capability_allows(caps, "filesystem", plugin_root=root,
                             path=os.path.join(root, "other", "a.txt"),
                             method="write")[0] is False


def test_invalid_capabilities_fail_closed():
    cases = [
        {"network": {"enabled": True, "domains": ["file:///tmp"]}},
        {"network": {"enabled": True, "domains": ["example.com"],
                     "methods": ["TRACE"]}},
        {"filesystem": {"read": ["../../secret"]}},
        {"filesystem": {"read": ["C:/Windows/win.ini"]}},
        {"process": {"enabled": True, "allow_argv": [["cmd.exe", "/c", "dir"]]}},
        {"process": {"enabled": True, "allow_argv": [["python", "x;whoami"]]}},
        {"config": {"read_secrets": False, "public_keys": ["api_key"]}},
    ]
    for caps in cases:
        r = validate_capabilities({"name": "demo", "capabilities": caps})
        assert r["ok"] is False, caps


def test_process_requires_exact_fixed_argv():
    manifest = _valid_manifest()
    manifest["capabilities"]["process"] = {
        "enabled": True,
        "allow_argv": [["python", "-V"]],
    }
    caps = validate_capabilities(manifest)["capabilities"]
    assert capability_allows(caps, "process", argv=["python", "-V"])[0] is True
    assert capability_allows(caps, "process", argv=["python", "-c", "print(1)"])[0] is False


def test_config_public_keys_and_secret_denial():
    manifest = _valid_manifest()
    caps = validate_capabilities(manifest)["capabilities"]
    assert capability_allows(caps, "config", key="theme")[0] is True
    assert capability_allows(caps, "config", key="api_key")[0] is False


def test_plugin_api_integration_exposes_capabilities():
    from core.plugin_api import validate_plugin_manifest
    r = validate_plugin_manifest(_valid_manifest(), "from core.safe import safe\n")
    assert r["ok"] is True, r
    assert r["capability_legacy"] is False
    assert r["risk_level"] == "medium"
    assert r["capabilities"]["network"]["enabled"] is True


def test_permission_center_capability_decisions_are_audited(tmp_path):
    from core.permission_center import PermissionCenter

    class FakePermissionTrunk:
        base = str(tmp_path)
        config = {}

    pc = PermissionCenter(FakePermissionTrunk())
    manifest = _valid_manifest()
    caps = validate_capabilities(manifest)["capabilities"]

    denied = pc.authorize_capability("demo", caps, "network",
                                     domain="evil.test", method="GET")
    assert denied["allow"] is False
    assert denied["requires_confirm"] is False

    need_confirm = pc.authorize_capability(
        "demo", caps, "network", domain="api.example.com", method="GET")
    assert need_confirm["allow"] is False
    assert need_confirm["requires_confirm"] is True

    pc.approve("capability:demo:network", scope="session")
    allowed = pc.authorize_capability(
        "demo", caps, "network", domain="api.example.com", method="GET")
    assert allowed["allow"] is True

    events = pc.list_audit(50)
    assert any(e.get("subject") == "capability:demo:network"
               and e.get("decision") == "deny" for e in events)
    assert any(e.get("subject") == "capability:demo:network"
               and e.get("decision") == "allow" for e in events)


def test_online_plugin_manifest_can_carry_capabilities(tmp_path):
    from modules.installed.plugin_market import PluginMarket

    class FakeMarketTrunk:
        base = str(tmp_path)
        config = {}
        modules = {}

        def _log(self, *_a, **_k):
            pass

    from core.plugin_capabilities import plugin_manifest_info
    PluginMarket(FakeMarketTrunk())
    info = plugin_manifest_info(_valid_manifest())
    assert info["risk_level"] == "medium"
    assert "网络" in info["capability_summary"]
    assert info["signature_status"] == "unsigned"
