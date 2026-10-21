# -*- coding: utf-8 -*-
"""小6插件标准 v2.1 落地组件测试。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.plugin_tier import (  # noqa: E402
    L1_EXEMPT_CLAUSES, check_manifest, derive, derive_risk, derive_tier,
    requires_strict_review,
)


def _caps(**over):
    base = {"network": {"enabled": False, "domains": [], "methods": []},
            "filesystem": {"read": [], "write": []},
            "process": {"enabled": False, "allow_argv": []},
            "ui_control": {"enabled": False},
            "config": {"read_secrets": False, "public_keys": [],
                       "secret_names": []}}
    base.update(over)
    return base


# ---------------- 分级（§0.3） ----------------
def test_tier_l1_for_clean_plugin():
    assert derive_tier(_caps()) == "L1"
    assert derive_risk(_caps()) == "low"
    assert requires_strict_review(_caps()) is False
    assert L1_EXEMPT_CLAUSES


def test_tier_l2_for_network_or_write():
    assert derive_tier(_caps(network={"enabled": True,
                                      "domains": ["api.example.com"],
                                      "methods": ["GET"]})) == "L2"
    assert derive_tier(_caps(filesystem={"read": [],
                                         "write": ["data/plugin_data/x/a"]})) == "L2"
    assert derive_risk(_caps(network={"enabled": True,
                                      "domains": ["a.com"],
                                      "methods": ["GET"]})) == "medium"


def test_tier_l3_for_process_ui_or_secrets():
    for caps in (_caps(process={"enabled": True, "allow_argv": [["python"]]}),
                 _caps(ui_control={"enabled": True}),
                 _caps(config={"read_secrets": True,
                               "public_keys": [],
                               "secret_names": ["k"]})):
        assert derive_tier(caps) == "L3"
        assert derive_risk(caps) == "high"
        assert requires_strict_review(caps) is True


def test_check_manifest_detects_mismatch():
    caps = _caps()
    r = check_manifest({"capabilities": caps, "plugin_tier": "L3",
                        "risk_level": "high"})
    assert r["ok"] is False
    assert {m["field"] for m in r["mismatches"]} == {"plugin_tier", "risk_level"}


def test_check_manifest_accepts_consistent_values():
    caps = _caps()
    r = check_manifest({"capabilities": caps, "plugin_tier": "L1",
                        "risk_level": "low"})
    assert r["ok"] is True and r["mismatches"] == []


# ---------------- 审计（N15） ----------------
def test_audit_record_has_required_fields(tmp_path):
    from core.plugin_audit import PluginAudit, REQUIRED_FIELDS
    a = PluginAudit(str(tmp_path))
    rec = a.record(plugin="p", action="call", capability="network",
                   allowed=True, detail="ok", version="1.0.0", session_id="s")
    for key in REQUIRED_FIELDS:
        assert key in rec, key
    assert rec["ts"].endswith("Z")


def test_audit_redacts_secrets(tmp_path):
    from core.plugin_audit import PluginAudit
    a = PluginAudit(str(tmp_path))
    rec = a.record(plugin="p", action="call", detail="token=secret-value-123456",
                   extra={"api_key": "sk-abcdefghijklmnop"})
    dumped = json.dumps(rec, ensure_ascii=False)
    assert "secret-value-123456" not in dumped
    assert "sk-abcdefghijklmnop" not in dumped


def test_audit_schema_and_stats(tmp_path):
    from core.plugin_audit import PluginAudit
    a = PluginAudit(str(tmp_path))
    a.record(plugin="p", action="a", allowed=True)
    a.record(plugin="p", action="b", allowed=False)
    assert a.validate_schema()["ok"] is True
    st = a.stats()
    assert st["records"] == 2 and st["denied"] == 1


def test_audit_purge_expired(tmp_path):
    from core.plugin_audit import PluginAudit
    a = PluginAudit(str(tmp_path), retention_days=1)
    a.record(plugin="p", action="old")
    removed = a.purge_expired(now=__import__("time").time() + 10 * 86400)
    assert removed == 1
    assert a.stats()["records"] == 0


# ---------------- 熔断与限额（N13） ----------------
def test_circuit_breaker_opens_and_recovers():
    from core.plugin_limits import CircuitBreaker
    now = [1000.0]
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10,
                        clock=lambda: now[0])
    assert cb.allow() is True
    cb.record_failure("x")
    assert cb.state() == "closed"
    cb.record_failure("y")
    assert cb.state() == "open"
    assert cb.allow() is False
    err = cb.error()["error"]
    assert err["code"] == "PLUGIN_CIRCUIT_OPEN" and err["retryable"] is True
    now[0] += 11
    assert cb.state() == "half_open"
    cb.record_success()
    assert cb.state() == "closed"


def test_rate_limiter_per_minute():
    from core.plugin_limits import RateLimiter
    now = [1000.0]
    rl = RateLimiter(per_minute=3, clock=lambda: now[0])
    assert all(rl.allow() for _ in range(3))
    assert rl.allow() is False
    now[0] += 61
    assert rl.allow() is True


def test_plugin_limits_write_quota():
    from core.plugin_limits import PluginLimits
    lim = PluginLimits(write_bytes=1000)
    assert lim.check_write(500) is None
    assert lim.check_write(600)["error"]["code"] == "PLUGIN_RESOURCE_EXHAUSTED"


def test_plugin_limits_network_and_breaker():
    from core.plugin_limits import PluginLimits
    lim = PluginLimits(network_per_minute=1, failure_threshold=1)
    assert lim.check_network() is None
    assert lim.check_network()["error"]["code"] == "PLUGIN_RESOURCE_EXHAUSTED"
    assert lim.before_call() is None
    lim.after_call(False, "boom")
    assert lim.before_call()["error"]["code"] == "PLUGIN_CIRCUIT_OPEN"


# ---------------- capabilities v2.1 端口规则 ----------------
def test_loopback_with_port_allowed():
    from core.plugin_capabilities import validate_capabilities
    r = validate_capabilities({"name": "x", "capabilities": {
        "network": {"enabled": True,
                    "domains": ["127.0.0.1:5000", "localhost:8080"],
                    "methods": ["GET"]}}})
    assert r["ok"] is True, r["errors"]


def test_non_loopback_with_port_rejected():
    from core.plugin_capabilities import validate_capabilities
    r = validate_capabilities({"name": "x", "capabilities": {
        "network": {"enabled": True, "domains": ["api.example.com:8080"],
                    "methods": ["GET"]}}})
    assert r["ok"] is False


def test_secret_names_declared():
    from core.plugin_capabilities import validate_capabilities
    r = validate_capabilities({"name": "x", "capabilities": {
        "config": {"read_secrets": True, "secret_names": ["weather_key"]}}})
    assert r["ok"] is True
    assert r["capabilities"]["config"]["secret_names"] == ["weather_key"]


# ---------------- manifest v2.1 字段 ----------------
def test_manifest_has_v21_fields():
    m = json.load(open(os.path.join(BASE, "modules_repo", "manifest.json"),
                       encoding="utf-8-sig"))
    import re as _re
    for meta in m:
        for key in ("license", "author", "min_host_version",
                    "plugin_tier", "risk_level"):
            assert key in meta, "%s 缺 %s" % (meta.get("name"), key)
        assert _re.match(r"^\d+\.\d+\.\d+", str(meta["version"])), \
            "%s version 不是三段式: %s" % (meta["name"], meta["version"])
        assert meta["plugin_tier"] in ("L1", "L2", "L3")
        assert meta["risk_level"] in ("low", "medium", "high")


def test_manifest_tier_matches_derivation():
    m = json.load(open(os.path.join(BASE, "modules_repo", "manifest.json"),
                       encoding="utf-8-sig"))
    for meta in m:
        r = check_manifest(meta)
        assert r["ok"], "%s 分级不一致: %s" % (meta.get("name"), r["mismatches"])


# ---------------- 工具级门禁 ----------------
def test_new_gates_pass():
    sys.path.insert(0, os.path.join(BASE, "tools"))
    import check_plugin_deps as deps
    import check_plugin_quality as quality
    import check_plugin_security as security
    import check_plugin_tier as tier
    assert quality.check_all()["errors"] == 0
    assert tier.main(["--json"]) == 0
    assert deps.main(["--ast", "--json"]) == 0
    assert security.main(["--json"]) == 0
