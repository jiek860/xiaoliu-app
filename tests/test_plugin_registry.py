# -*- coding: utf-8 -*-
"""Plugin version, trust and update selection tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_registry import (  # noqa: E402
    InstallLedger, compare_versions, host_compatibility, manifest_product_info,
    select_update, trust_tier, version_tuple,
)


def _meta(version="1.2.0", **extra):
    data = {"name": "demo", "version": version, "api_version": "1.0",
            "first_party": False, "signature": "signed",
            "capabilities": {"network": {"enabled": True,
                                          "domains": ["api.example.com"]}}}
    data.update(extra)
    return data


def test_semver_compare_and_tuple():
    assert version_tuple("v1.2.3") == (1, 2, 3)
    assert compare_versions("1.2.3", "1.2.2") > 0
    assert compare_versions("1.2", "1.2.0") == 0


def test_trust_tiers():
    assert trust_tier(_meta(first_party=True)) == "official"
    assert trust_tier(_meta()) == "signed"
    assert trust_tier(_meta(signature="")) == "unsigned"


def test_host_compatibility_and_blocked_update():
    compatible = _meta("1.3.0", min_host_version="25.0.0")
    blocked = _meta("2.0.0", min_host_version="99.0.0")
    info = manifest_product_info(compatible, "25.2.23", "1.0")
    assert info["compatible"] is True
    assert info["risk_level"] == "medium"
    out = select_update("1.2.0", [compatible, blocked], "25.2.23", "1.0")
    assert out["update_available"] is True
    assert out["latest"]["version"] == "1.3.0"
    assert out["blocked"][0]["version"] == "2.0.0"


def test_api_version_mismatch_is_blocked():
    r = host_compatibility(_meta(api_version="2.0"), "25.2.23", "1.0")
    assert r["ok"] is False
    assert r["reasons"]


def test_install_ledger_records_history(tmp_path):
    ledger = InstallLedger(str(tmp_path))
    ledger.record("demo", "1.0.0", "install")
    ledger.record("demo", "1.1.0", "update")
    assert ledger.latest("demo")["version"] == "1.1.0"
    assert len(ledger.history("demo")) == 2
    again = InstallLedger(str(tmp_path))
    assert again.latest("demo")["version"] == "1.1.0"
