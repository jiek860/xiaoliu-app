# -*- coding: utf-8 -*-
"""Local multi-user/team policy: roles, isolation, central config and audit."""
from __future__ import annotations

import json
import os
import time

from core.path_safety import safe_join, safe_name
from core.redaction import redact_mapping

ROLES = ("owner", "admin", "editor", "viewer", "auditor")
ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {"user:manage", "config:write", "config:read", "data:read",
              "data:write", "audit:read", "plugin:manage", "mcp:manage"},
    "editor": {"config:read", "data:read", "data:write", "plugin:use",
               "mcp:use"},
    "viewer": {"config:read", "data:read", "plugin:use"},
    "auditor": {"config:read", "data:read", "audit:read"},
}


def has_permission(role, permission):
    perms = ROLE_PERMISSIONS.get(str(role or "").lower(), set())
    return "*" in perms or str(permission) in perms


class TeamStore:
    def __init__(self, base):
        self.base = os.path.realpath(os.path.abspath(base))
        self.dir = os.path.join(self.base, "data", "team")
        os.makedirs(self.dir, exist_ok=True)
        self.users_path = os.path.join(self.dir, "users.json")
        self.config_path = os.path.join(self.dir, "central_config.json")
        self.audit_path = os.path.join(self.dir, "audit.jsonl")
        self.users = self._load(self.users_path, {})
        if not self.users:
            self.users["local"] = {"name": "本地用户", "role": "owner",
                                   "disabled": False, "created_at": time.time()}
            self._save(self.users_path, self.users)

    @staticmethod
    def _load(path, default):
        try:
            data = json.load(open(path, encoding="utf-8-sig"))
            return data if isinstance(data, type(default)) else default
        except Exception:
            return default

    @staticmethod
    def _save(path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def add_user(self, user_id, name="", role="viewer", requester="local"):
        actor = self.check(requester, "user:manage")
        if not actor["ok"]:
            return actor
        uid = safe_name(user_id, default="", max_len=80)
        if not uid:
            return {"ok": False, "error": "invalid user_id"}
        if str(role).lower() not in ROLES:
            return {"ok": False, "error": "invalid role"}
        self.users[uid] = {"name": str(name or uid), "role": str(role).lower(),
                           "disabled": False, "created_at": time.time()}
        self._save(self.users_path, self.users)
        self.audit(requester, "user:add", uid)
        return {"ok": True, "user": self.users[uid]}

    def set_role(self, user_id, role, requester="local"):
        actor = self.check(requester, "user:manage")
        if not actor["ok"]:
            return actor
        if user_id not in self.users:
            return {"ok": False, "error": "user not found"}
        if str(role).lower() not in ROLES:
            return {"ok": False, "error": "invalid role"}
        self.users[user_id]["role"] = str(role).lower()
        self._save(self.users_path, self.users)
        self.audit(requester, "user:role", user_id, {"role": role})
        return {"ok": True, "user": self.users[user_id]}

    def disable_user(self, user_id, requester="local"):
        actor = self.check(requester, "user:manage")
        if not actor["ok"]:
            return actor
        if user_id not in self.users:
            return {"ok": False, "error": "user not found"}
        self.users[user_id]["disabled"] = True
        self._save(self.users_path, self.users)
        self.audit(requester, "user:disable", user_id)
        return {"ok": True}

    def list_users(self, requester="local"):
        actor = self.check(requester, "user:manage")
        if not actor["ok"]:
            return actor
        return {"ok": True, "users": {k: dict(v) for k, v in self.users.items()}}

    def check(self, user_id, permission):
        user = self.users.get(str(user_id or ""))
        if not user or user.get("disabled"):
            return {"ok": False, "error": "user disabled or missing",
                    "user": user_id}
        role = str(user.get("role") or "viewer")
        ok = has_permission(role, permission)
        return {"ok": ok, "role": role, "permission": permission,
                "error": "" if ok else "permission denied"}

    def user_root(self, user_id):
        uid = safe_name(user_id, default="", max_len=80)
        if not uid:
            return None
        root = os.path.join(self.base, "data", "users", uid)
        os.makedirs(root, exist_ok=True)
        return root

    def get_central_config(self, requester="local"):
        actor = self.check(requester, "config:read")
        if not actor["ok"]:
            return actor
        return {"ok": True, "config": self._load(self.config_path, {})}

    def set_central_config(self, values, requester="local"):
        actor = self.check(requester, "config:write")
        if not actor["ok"]:
            return actor
        if not isinstance(values, dict):
            return {"ok": False, "error": "values must be an object"}
        cfg = self._load(self.config_path, {})
        cfg.update(values)
        self._save(self.config_path, cfg)
        self.audit(requester, "config:write", "central", {"keys": sorted(values)})
        return {"ok": True, "config": cfg}

    def apply_central_config(self, user_config, user_id):
        """Viewer/editor receive centrally managed keys, user keys may not override."""
        cfg = dict(user_config or {})
        central = self._load(self.config_path, {})
        cfg.update(central)
        return cfg

    def audit(self, actor, action, target="", extra=None):
        rec = redact_mapping({"time": time.time(), "actor": str(actor),
                              "action": str(action), "target": str(target),
                              "extra": dict(extra or {})})
        try:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return rec

    def export_audit(self, out_path, requester="local", limit=5000):
        actor = self.check(requester, "audit:read")
        if not actor["ok"]:
            return actor
        records = []
        try:
            for line in open(self.audit_path, encoding="utf-8").read().splitlines()[-limit:]:
                if line.strip():
                    records.append(json.loads(line))
        except Exception:  # 静默是故意的
            pass
        target = os.path.abspath(out_path)
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"audit": records}, f, ensure_ascii=False, indent=2)
        self.audit(requester, "audit:export", target, {"count": len(records)})
        return {"ok": True, "path": target, "count": len(records)}
