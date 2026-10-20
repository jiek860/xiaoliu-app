# -*- coding: utf-8 -*-
"""Team RBAC, isolation, central config and audit export tests."""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.team_policy import TeamStore, has_permission  # noqa: E402


def test_role_permissions():
    assert has_permission("owner", "anything")
    assert has_permission("admin", "config:write")
    assert not has_permission("viewer", "config:write")
    assert has_permission("auditor", "audit:read")


def test_user_management_and_rbac(tmp_path):
    t = TeamStore(str(tmp_path))
    assert t.add_user("alice", "Alice", "editor")["ok"]
    assert t.check("alice", "data:write")["ok"]
    assert not t.check("alice", "config:write")["ok"]
    assert t.set_role("alice", "admin")["ok"]
    assert t.check("alice", "config:write")["ok"]


def test_viewer_cannot_manage_users(tmp_path):
    t = TeamStore(str(tmp_path))
    t.add_user("bob", "Bob", "viewer")
    r = t.add_user("eve", "Eve", "viewer", requester="bob")
    assert r["ok"] is False


def test_user_isolation_root(tmp_path):
    t = TeamStore(str(tmp_path))
    a = t.user_root("alice")
    b = t.user_root("bob")
    assert a and b and a != b
    assert os.path.isdir(a) and os.path.isdir(b)


def test_central_config_overrides_user_config(tmp_path):
    t = TeamStore(str(tmp_path))
    assert t.set_central_config({"model_mode": "云端模型",
                                 "allow_inprocess_plugins": False})["ok"]
    merged = t.apply_central_config({"model_mode": "本地模型",
                                     "allow_inprocess_plugins": True}, "local")
    assert merged["model_mode"] == "云端模型"
    assert merged["allow_inprocess_plugins"] is False


def test_audit_export_redacts_and_requires_permission(tmp_path):
    t = TeamStore(str(tmp_path))
    t.add_user("viewer1", "Viewer", "viewer")
    assert t.check("viewer1", "audit:read")["ok"] is False
    t.audit("local", "test", "x", {"api_key": "secret-value"})
    out = tmp_path / "audit.json"
    r = t.export_audit(str(out))
    assert r["ok"] and r["count"] >= 1
    raw = out.read_text(encoding="utf-8")
    assert "secret-value" not in raw
    assert "***REDACTED***" in raw


def test_central_config_applied_by_load_config(tmp_path):
    from core.config import load_config
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.json").write_text("{}", encoding="utf-8")
    central = data / "team"
    central.mkdir()
    (central / "central_config.json").write_text(
        '{"model_mode":"云端模型","allow_inprocess_plugins":false}',
        encoding="utf-8")
    cfg = load_config(str(data / "config.json"))
    assert cfg["model_mode"] == "云端模型"
    assert cfg["allow_inprocess_plugins"] is False


def test_auth_binds_license_user_to_team_role_and_disable(tmp_path, monkeypatch):
    from core.auth import Auth
    class T:
        base = str(tmp_path)
        config = {}
    a = Auth(T())
    monkeypatch.setattr(a, "_verify_code",
                        lambda code: (True, "ok", {"expire": "永久"}))
    assert a.activate("alice", "FAKE-CODE")["ok"]
    r = a.login("alice")
    assert r["ok"] and r["role"] == "viewer"
    assert a.whoami()["role"] == "viewer"
    assert a.has_permission("data:read")
    assert not a.has_permission("config:write")
    assert a.team.disable_user("alice")["ok"]
    a.logout()
    assert a.login("alice")["ok"] is False
