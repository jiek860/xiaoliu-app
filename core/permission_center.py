# -*- coding: utf-8 -*-
"""统一权限中心。

工具表里的 readonly/confirm/danger 只是声明；真正是否执行由这里决定。
支持 once / session / always 规则、过期、紧急锁定和审计。
"""
import json
import os
import threading
import time
import urllib.parse

from core import security_policy
from core.audit_log import AuditLog

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class PermissionCenter:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        self.dir = os.path.join(self.base, "data", "security")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "permissions.json")
        self.lock_path = os.path.join(self.dir, "lockdown.json")
        self.audit = AuditLog(self.base)
        self._lock = threading.RLock()
        self._session_rules = []
        self.rules = self._load()
        self.locked = self._load_lockdown()

    def _load(self):
        try:
            d = json.load(open(self.path, encoding="utf-8"))
            return list(d.get("rules") or [])
        except Exception:
            return []

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with self._lock:
                json.dump({"version": 1, "rules": self.rules},
                          open(tmp, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def _load_lockdown(self):
        try:
            return bool(json.load(open(self.lock_path, encoding="utf-8"))
                        .get("locked", False))
        except Exception:
            return False

    def lockdown(self, enabled=True):
        self.locked = bool(enabled)
        try:
            tmp = self.lock_path + ".tmp"
            json.dump({"locked": self.locked, "time": time.time()},
                      open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, self.lock_path)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback
        self.audit.append({"subject": "system:lockdown",
                           "decision": "allow" if not enabled else "deny",
                           "result": "locked" if enabled else "unlocked",
                           "reason": "紧急停止"})
        return {"ok": True, "locked": self.locked}

    def _match(self, subject):
        now = time.time()
        out = []
        for r in list(self.rules) + list(self._session_rules):
            if r.get("subject") != subject:
                continue
            exp = float(r.get("expires_at") or 0)
            if exp and exp <= now:
                continue
            out.append(r)
        return out

    @staticmethod
    def _extract_paths(args):
        paths = []
        def walk(obj, key=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, str(k))
            elif isinstance(obj, list):
                for v in obj:
                    walk(v, key)
            elif isinstance(obj, str):
                if key in ("path", "file", "filename", "src", "dst"):
                    paths.append(obj)
                elif key == "spec" and obj.strip().startswith("{"):
                    try:
                        walk(json.loads(obj))
                    except Exception as e:
                        _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback
        walk(args or {})
        return paths

    @staticmethod
    def _extract_domains(args):
        domains = []
        def walk(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)
            elif isinstance(obj, str):
                if "://" in obj:
                    try:
                        h = urllib.parse.urlparse(obj).hostname
                        if h:
                            domains.append(h.lower())
                    except Exception as e:
                        _x6_swallowed(__name__, e, "best-effort fallback")  # 静默是故意的 - defensive fallback
        walk(args or {})
        return domains

    def suggest_constraints(self, subject, args):
        paths = self._extract_paths(args)
        if paths:
            p = os.path.abspath(paths[0])
            return {"path_prefix": os.path.dirname(p) + os.sep}
        domains = self._extract_domains(args)
        if domains:
            return {"domain": domains[0]}
        return {}

    @staticmethod
    def _rule_constraints_ok(rule, args):
        c = rule.get("constraints") or {}
        if not c:
            return True
        paths = PermissionCenter._extract_paths(args)
        if c.get("path_prefix"):
            prefix = os.path.normcase(os.path.abspath(c["path_prefix"]))
            if not paths:
                return False
            for p in paths:
                pn = os.path.normcase(os.path.abspath(p))
                if not (pn == prefix or pn.startswith(prefix)):
                    return False
        exts = c.get("file_ext")
        if exts:
            if not paths:
                return False
            if any(os.path.splitext(p)[1].lower() not in exts for p in paths):
                return False
        dom = c.get("domain")
        if dom:
            ds = PermissionCenter._extract_domains(args)
            if not ds or any(d != dom.lower() and not d.endswith("." + dom.lower())
                             for d in ds):
                return False
        return True

    def approve(self, subject, scope="once", expires=None, reason="用户确认",
                constraints=None):
        now = time.time()
        exp = 0
        if expires:
            exp = float(expires)
        rec = {"id": "perm_%d" % int(now * 1000), "subject": subject,
               "scope": scope, "decision": "allow",
               "expires_at": exp, "created_at": now, "reason": reason,
               "constraints": dict(constraints or {})}
        if scope == "once":
            self._session_rules.append(dict(rec, _once=True))
        elif scope == "session":
            self._session_rules.append(rec)
        else:
            self.rules.append(rec)
            self._save()
        self.audit.append({"subject": subject, "decision": "allow",
                           "result": "approved", "reason": reason})
        return {"ok": True, "rule": rec}

    def _touch_rule(self, rule, subject, args):
        try:
            rule["hit_count"] = int(rule.get("hit_count", 0)) + 1
            rule["last_hit_at"] = time.time()
            rule["last_args_hash"] = self._arg_hash(args)
            if rule in self.rules:
                self._save()
        except Exception as e:  # 静默是故意的 - 命中统计失败不影响授权
            _x6_swallowed(__name__, e, "best-effort fallback")

    @staticmethod
    def _arg_hash(args):
        import hashlib
        try:
            raw = json.dumps(args or {}, ensure_ascii=False, sort_keys=True,
                             default=str)
        except Exception:
            raw = repr(args)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def update_constraints(self, rule_id, constraints):
        for r in list(self.rules) + list(self._session_rules):
            if r.get("id") == rule_id:
                if not isinstance(constraints, dict):
                    return {"ok": False, "error": "constraints 必须是对象"}
                r["constraints"] = dict(constraints)
                if r in self.rules:
                    self._save()
                self.audit.append({
                    "subject": "system:permission",
                    "decision": "allow", "result": "constraints_updated",
                    "reason": str(constraints)[:200]})
                return {"ok": True, "rule": r}
        return {"ok": False, "error": "规则不存在"}

    def revoke(self, rule_id):
        before = len(self.rules)
        had_session = any(r.get("id") == rule_id for r in self._session_rules)
        self.rules = [r for r in self.rules if r.get("id") != rule_id]
        self._session_rules = [r for r in self._session_rules
                               if r.get("id") != rule_id]
        changed = len(self.rules) < before or had_session
        if changed:
            self._save()
        self.audit.append({"subject": "system:permission",
                           "decision": "deny", "result": "revoked",
                           "reason": str(rule_id)[:80]})
        return changed

    def list_rules(self):
        now = time.time()
        return [r for r in (self.rules + self._session_rules)
                if not float(r.get("expires_at") or 0)
                or float(r.get("expires_at") or 0) > now]

    def list_audit(self, limit=100):
        return self.audit.list_recent(limit)

    def _consume_once(self, subject):
        for i, r in enumerate(list(self._session_rules)):
            if r.get("subject") == subject and r.get("_once"):
                self._session_rules.pop(i)
                return

    def authorize(self, subject, *, info=None, args=None, context=None):
        info = info or {}
        policy = security_policy.classify(subject, info)
        readonly = bool(policy.get("readonly"))
        danger = bool(policy.get("danger"))
        confirm = bool(policy.get("confirm") or danger)

        if getattr(self.trunk, "_remote_tool_locked", False) and not self._remote_allowed():
            if not (readonly and not confirm):
                return {"allow": False, "requires_confirm": False,
                        "reason": "远程会话已禁用该工具", "risk": policy.get("risk")}

        if self.locked and not readonly:
            return {"allow": False, "requires_confirm": False,
                    "reason": "系统处于紧急锁定状态", "risk": policy.get("risk")}

        rules = self._match(subject)
        for r in rules:
            if not self._rule_constraints_ok(r, args):
                continue
            self._touch_rule(r, subject, args)
            if r.get("decision") == "deny":
                return {"allow": False, "requires_confirm": False,
                        "reason": "用户已拒绝", "risk": policy.get("risk")}
            if r.get("decision") == "allow":
                if r.get("_once"):
                    self._consume_once(subject)
                return {"allow": True, "requires_confirm": False,
                        "reason": "已有允许规则", "risk": policy.get("risk")}

        if danger:
            rule = security_policy.danger_rule(subject, info)
            if rule and not self._rule_allows(rule):
                return {"allow": False, "requires_confirm": False,
                        "reason": "规则「%s」未开启" % rule,
                        "risk": policy.get("risk")}
        if readonly and not confirm:
            return {"allow": True, "requires_confirm": False,
                    "reason": "只读工具", "risk": policy.get("risk")}
        return {"allow": False, "requires_confirm": True,
                "reason": "需要用户确认", "risk": policy.get("risk")}

    def authorize_capability(self, plugin_name, capabilities, kind, *,
                             plugin_root=None, path=None, domain=None,
                             method="GET", argv=None, key=None, context=None):
        """Authorize a plugin/MCP capability through the same rules/audit store.

        The target operation is validated against the normalized capability
        manifest first; a previous once/session/always grant can then satisfy
        user confirmation. Missing capabilities are denied, never defaulted on.
        """
        from core.plugin_capabilities import capability_allows

        subject = "capability:%s:%s" % (plugin_name, kind)
        decision, reason = capability_allows(
            capabilities, kind, domain=domain, method=method,
            plugin_root=plugin_root, path=path, argv=argv, key=key)
        if not decision:
            self.audit.append({
                "subject": subject, "decision": "deny", "result": "capability_denied",
                "reason": reason, "args_preview": str(context or "")[:300]})
            return {"allow": False, "requires_confirm": False,
                    "reason": reason, "capability": kind}

        if self.locked and kind not in ("config",):
            self.audit.append({
                "subject": subject, "decision": "deny", "result": "lockdown",
                "reason": "系统处于紧急锁定状态"})
            return {"allow": False, "requires_confirm": False,
                    "reason": "系统处于紧急锁定状态", "capability": kind}

        for rule in self._match(subject):
            if rule.get("decision") == "allow":
                if rule.get("_once"):
                    self._consume_once(subject)
                self.audit.append({
                    "subject": subject, "decision": "allow",
                    "result": "capability_allowed", "reason": "已有授权规则",
                    "args_preview": str(context or "")[:300]})
                return {"allow": True, "requires_confirm": False,
                        "reason": "已有授权规则", "capability": kind}
            if rule.get("decision") == "deny":
                return {"allow": False, "requires_confirm": False,
                        "reason": "用户已拒绝", "capability": kind}

        high_risk = kind in ("process", "ui_control")
        requires_confirm = high_risk or kind in ("network", "filesystem")
        if not requires_confirm:
            self.audit.append({
                "subject": subject, "decision": "allow",
                "result": "capability_allowed", "reason": reason,
                "args_preview": str(context or "")[:300]})
            return {"allow": True, "requires_confirm": False,
                    "reason": reason, "capability": kind}
        return {"allow": False, "requires_confirm": True,
                "reason": "能力 %s 需要用户确认" % kind,
                "capability": kind}

    def _remote_allowed(self):
        try:
            return bool(getattr(self.trunk, "_remote_tools_allowed", False)
                        or (getattr(self.trunk, "config", {}) or {})
                        .get("bot_allow_tools", False))
        except Exception:
            return False

    def _rule_allows(self, rule):
        try:
            return bool(self.trunk.rule(rule, False))
        except Exception:
            return False


_CACHE = {}


def get_permission_center(trunk):
    key = id(trunk) if trunk is not None else 0
    pc = _CACHE.get(key)
    if pc is None:
        pc = PermissionCenter(trunk)
        _CACHE[key] = pc
    return pc
