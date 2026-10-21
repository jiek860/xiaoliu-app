# -*- coding: utf-8 -*-
"""v2.1 新增工具级代码的覆盖率补充测试。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))


# ---------------- broker：熔断/审计/凭据 ----------------
def _caps(**over):
    base = {"network": {"enabled": False, "domains": [], "methods": []},
            "filesystem": {"read": [], "write": []},
            "process": {"enabled": False, "allow_argv": []},
            "ui_control": {"enabled": False},
            "config": {"read_secrets": False, "public_keys": [],
                       "secret_names": []}}
    base.update(over)
    return base


class _PC:
    def __init__(self, allow=True):
        self.allow = allow

    def authorize_capability(self, *_a, **_k):
        return {"allow": self.allow, "reason": "test"}

    def approve(self, *_a, **_k):
        return True


class _Trunk:
    config = {"secret_key": "s3cr3t-value", "theme": "dark"}


def _broker(tmp_path, caps=None):
    from core.plugin_broker import PluginBroker
    return PluginBroker(str(tmp_path), "demo", os.path.join(str(tmp_path), "p.py"),
                        caps or _caps(), trunk=_Trunk(),
                        permission_center=_PC(), timeout=2)


def test_broker_audit_event_writes_record(tmp_path):
    b = _broker(tmp_path)
    b.set_identity(version="1.0.0", session_id="sess-1")
    rec = b._audit_event("call", "network", True, "ok")
    assert rec["plugin"] == "demo"
    assert rec["version"] == "1.0.0"
    assert rec["session_id"] == "sess-1"
    rows = b.audit.read()
    assert rows and rows[-1]["action"] == "call"


def test_broker_get_secret_denied_without_declaration(tmp_path):
    b = _broker(tmp_path)
    try:
        b._config_get_secret("secret_key")
        assert False, "应拒绝"
    except PermissionError as e:
        assert "read_secrets" in str(e)
    assert b.audit.read()[-1]["allowed"] is False


def test_broker_get_secret_allowed_when_declared(tmp_path):
    caps = _caps(config={"read_secrets": True, "public_keys": [],
                         "secret_names": ["secret_key"]})
    b = _broker(tmp_path, caps)
    assert b._config_get_secret("secret_key") == "s3cr3t-value"
    # 审计只记名字，不落值
    assert "s3cr3t-value" not in json.dumps(b.audit.read(), ensure_ascii=False)


def test_broker_get_secret_rejects_unlisted_name(tmp_path):
    caps = _caps(config={"read_secrets": True, "public_keys": [],
                         "secret_names": ["other"]})
    b = _broker(tmp_path, caps)
    try:
        b._config_get_secret("secret_key")
        assert False
    except PermissionError as e:
        assert "secret_names" in str(e)


def test_broker_write_quota_enforced(tmp_path):
    b = _broker(tmp_path)
    b.limits.write_bytes = 10
    try:
        b._write_file("out.txt", "x" * 100)
        assert False, "应拒绝超限写入"
    except PermissionError as e:
        assert "超过" in str(e) or "上限" in str(e)


def test_broker_network_rate_limit(tmp_path):
    b = _broker(tmp_path)
    b.limits.network.limit = 1
    b.limits.check_network()          # 用掉配额
    try:
        b._network_request({"url": "https://api.example.com/x", "method": "GET"})
        assert False, "应被限流"
    except PermissionError as e:
        assert "上限" in str(e) or "limit" in str(e).lower()


def test_broker_circuit_breaker_blocks_calls(tmp_path):
    b = _broker(tmp_path)
    b.limits.breaker.failure_threshold = 1
    b.limits.after_call(False, "boom")
    from core.plugin_broker import PluginBrokerError
    try:
        b.call_plugin()
        assert False
    except PluginBrokerError as e:
        assert "熔断" in str(e)


# ---------------- 工具脚本 ----------------
def test_verify_signature_algo_and_all():
    import verify_signature as vs
    assert vs.main(["--algo"]) == 0
    assert vs.main(["--all", "--json"]) == 0


def test_verify_signature_reports_missing_source(tmp_path):
    import verify_signature as vs
    signer = object()
    r = vs.verify_one({"name": "ghost", "file": "nope.py"}, signer,
                      {"signatures": [], "keys": []})
    assert r["ok"] is False and "源码不存在" in r["errors"][0]


def test_verify_signature_crl_blocks(tmp_path):
    import verify_signature as vs
    from core.plugin_signer import PluginSigner
    meta = json.load(open(os.path.join(BASE, "modules_repo", "manifest.json"),
                          encoding="utf-8-sig"))[0]
    signer = PluginSigner(BASE)
    raw = open(os.path.join(BASE, "modules_repo", meta["file"]), "rb").read()
    digest = signer.calc_hash_bytes(raw)
    fake = {"name": meta["name"], "file": meta["file"],
            "sha256": digest, "signature": meta["signature"]}
    r = vs.verify_one(fake, signer, {"signatures": [meta["signature"]],
                                     "keys": []})
    assert r["ok"] is False
    assert any("吊销" in e for e in r["errors"])


def test_check_plugin_deps_parse_and_cycles():
    import check_plugin_deps as cd
    assert cd.parse_dep("core:path_safety")["kind"] == "core"
    assert cd.parse_dep("plugin:notes@>=1.0.0")["name"] == "notes"
    assert cd.parse_dep("pkg:requests@>=2")["kind"] == "pkg"
    assert cd.parse_dep("bad-format") is None
    assert cd.parse_dep("plugin:notes") is None      # 缺版本范围
    cycles = cd.find_cycles({"a": {"b"}, "b": {"a"}, "c": set()})
    assert cycles and set(cycles[0][:2]) == {"a", "b"}


def test_check_plugin_tier_single_name():
    import check_plugin_tier as ct
    assert ct.main(["weather", "--json"]) == 0


def test_check_plugin_security_switches():
    import check_plugin_security as cs
    for args in (["--config", "--json"], ["--paths", "--json"],
                 ["--secrets", "--json"], ["--level", "L3", "--json"]):
        assert cs.main(args) == 0


def test_quality_gate_tolerates_unsigned_source_manifest():
    import check_plugin_quality as q
    r = q.check_module({"name": "x", "file": "nope.py", "signature": "",
                        "sha256": "", "api_version": "1.0",
                        "capabilities": _caps(),
                        "license": "L", "author": "A",
                        "min_host_version": "25.2.23",
                        "plugin_tier": "L1", "risk_level": "low",
                        "version": "1.0.0", "title": "t", "cls": "C",
                        "desc": "d", "group": "g", "first_party": True})
    # 源码缺失仍是 error，但"未签名"不应再是 error
    assert any("源码文件不存在" in e for e in r["errors"])
    assert not any("未签名" in e for e in r["errors"])
