# -*- coding: utf-8 -*-
"""Plugin capability manifest v2.

Signing answers *who* published a plugin. Capabilities answer *what the plugin
is allowed to touch at runtime*. This module is deliberately side-effect free:
it validates and normalizes manifests, but never executes plugin code.

Legacy plugins without a ``capabilities`` object are accepted for compatibility
but receive a deny-all capability set. A product release must either keep such
plugins disabled or require an explicit operator opt-in.
"""
from __future__ import annotations

import os
import re

CAPABILITY_SCHEMA_VERSION = "1.0"
CAPABILITY_KEYS = ("network", "filesystem", "process", "ui_control", "config")
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_DOMAIN_RE = re.compile(r"^(?:\*\.)?(?=.{3,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|passwd|credential|private)", re.I)
_SHELL_META = re.compile(r"[;&|<>`$%\r\n]")


def default_capabilities():
    return {
        "network": {"enabled": False, "domains": [], "methods": []},
        "filesystem": {"read": [], "write": []},
        "process": {"enabled": False, "allow_argv": []},
        "ui_control": {"enabled": False},
        "config": {"read_secrets": False, "public_keys": []},
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _bool(value, default=False):
    if value is None:
        return default
    return bool(value)


def _clean_domain(value):
    text = str(value or "").strip().lower().rstrip(".")
    if not text or "://" in text or "/" in text or ":" in text:
        return None
    if not _DOMAIN_RE.match(text):
        return None
    return text


def _clean_relpath(value, plugin_name=None):
    raw = str(value or "").strip().replace("\\", "/")
    if plugin_name:
        raw = raw.replace("{plugin_name}", str(plugin_name))
    if not raw or "\x00" in raw:
        return None
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts) or "."


def _validate_network(raw, errors, warnings):
    out = {"enabled": False, "domains": [], "methods": []}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        errors.append("capabilities.network must be an object")
        return out
    out["enabled"] = _bool(raw.get("enabled"))
    for item in _as_list(raw.get("domains")):
        domain = _clean_domain(item)
        if domain:
            out["domains"].append(domain)
        else:
            errors.append("capabilities.network.domains contains an invalid domain: %r" % (item,))
    for item in _as_list(raw.get("methods")):
        method = str(item or "").strip().upper()
        if method not in HTTP_METHODS:
            errors.append("capabilities.network.methods contains an invalid method: %r" % (item,))
        elif method not in out["methods"]:
            out["methods"].append(method)
    out["domains"] = sorted(set(out["domains"]))
    if out["enabled"] and not out["domains"]:
        errors.append("network.enabled requires at least one allowed domain")
    if out["enabled"] and not out["methods"]:
        out["methods"] = ["GET"]
    if not out["enabled"] and (out["domains"] or out["methods"]):
        warnings.append("network domains/methods are ignored because network.enabled is false")
    return out


def _validate_filesystem(raw, plugin_name, errors, warnings):
    out = {"read": [], "write": []}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        errors.append("capabilities.filesystem must be an object")
        return out
    allowed_keys = {"read", "write"}
    unknown = set(raw) - allowed_keys
    if unknown:
        warnings.append("unknown filesystem capability keys ignored: %s" % sorted(unknown))
    for action in ("read", "write"):
        for item in _as_list(raw.get(action)):
            path = _clean_relpath(item, plugin_name)
            if not path:
                errors.append("capabilities.filesystem.%s contains an invalid path: %r"
                              % (action, item))
                continue
            if plugin_name:
                root = "data/plugin_data/%s" % plugin_name
                if not (path == root or path.startswith(root + "/")):
                    errors.append("filesystem scope must stay under %s: %r" % (root, item))
                    continue
            if path not in out[action]:
                out[action].append(path)
    return out


def _validate_process(raw, errors, warnings):
    out = {"enabled": False, "allow_argv": []}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        errors.append("capabilities.process must be an object")
        return out
    out["enabled"] = _bool(raw.get("enabled"))
    for argv in _as_list(raw.get("allow_argv")):
        if not isinstance(argv, (list, tuple)) or not argv:
            errors.append("process.allow_argv entries must be non-empty arrays")
            continue
        clean = []
        bad = False
        for part in argv:
            text = str(part or "")
            if not text or "\x00" in text or _SHELL_META.search(text):
                bad = True
                break
            clean.append(text)
        if bad:
            errors.append("process.allow_argv contains shell metacharacters or empty args: %r"
                          % (argv,))
            continue
        banned = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh",
                  "pwsh.exe", "sh", "bash", "wscript", "wscript.exe",
                  "cscript", "cscript.exe"}
        exe = os.path.basename(clean[0]).lower()
        if exe in banned:
            errors.append("process.allow_argv may not use a shell/wrapper: %r" % (argv,))
        elif clean not in out["allow_argv"]:
            out["allow_argv"].append(clean)
    if out["enabled"] and not out["allow_argv"]:
        errors.append("process.enabled requires at least one fixed allow_argv entry")
    if not out["enabled"] and out["allow_argv"]:
        warnings.append("process.allow_argv is ignored because process.enabled is false")
    return out


def _validate_config(raw, errors, warnings):
    out = {"read_secrets": False, "public_keys": []}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        errors.append("capabilities.config must be an object")
        return out
    out["read_secrets"] = _bool(raw.get("read_secrets"))
    for item in _as_list(raw.get("public_keys")):
        key = str(item or "").strip()
        if not key:
            errors.append("config.public_keys contains an empty key")
        elif _SECRET_KEY_RE.search(key):
            errors.append("secret-looking config key cannot be public: %s" % key)
        elif key not in out["public_keys"]:
            out["public_keys"].append(key)
    if out["read_secrets"]:
        warnings.append("config.read_secrets grants access to secret material")
    return out


def risk_level(caps):
    network = caps.get("network") or {}
    filesystem = caps.get("filesystem") or {}
    process = caps.get("process") or {}
    ui = caps.get("ui_control") or {}
    config = caps.get("config") or {}
    reasons = []
    high = False
    if process.get("enabled"):
        high = True
        reasons.append("process execution")
    if ui.get("enabled"):
        high = True
        reasons.append("UI control")
    if config.get("read_secrets"):
        high = True
        reasons.append("secret access")
    if high:
        return "high", reasons
    if network.get("enabled"):
        reasons.append("network access")
    if filesystem.get("write"):
        reasons.append("filesystem write")
    if reasons:
        return "medium", reasons
    return "low", reasons or ["read-only or no declared capability"]


def validate_capabilities(meta, *, plugin_name=None):
    meta = dict(meta or {})
    plugin_name = plugin_name or meta.get("name") or meta.get("file") or ""
    if plugin_name.endswith(".py"):
        plugin_name = plugin_name[:-3]
    raw = meta.get("capabilities")
    legacy = raw is None
    errors, warnings = [], []
    caps = default_capabilities()
    if legacy:
        warnings.append("manifest has no capabilities; default deny-all applies")
    elif not isinstance(raw, dict):
        errors.append("capabilities must be an object")
    else:
        unknown = set(raw) - set(CAPABILITY_KEYS)
        if unknown:
            warnings.append("unknown capability sections ignored: %s" % sorted(unknown))
        caps["network"] = _validate_network(raw.get("network"), errors, warnings)
        caps["filesystem"] = _validate_filesystem(
            raw.get("filesystem"), plugin_name, errors, warnings)
        caps["process"] = _validate_process(raw.get("process"), errors, warnings)
        ui = raw.get("ui_control")
        if ui is not None and not isinstance(ui, dict):
            errors.append("capabilities.ui_control must be an object")
        else:
            caps["ui_control"] = {"enabled": _bool((ui or {}).get("enabled"))}
        caps["config"] = _validate_config(raw.get("config"), errors, warnings)
    level, reasons = risk_level(caps)
    return {
        "ok": not errors,
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "legacy": legacy,
        "capabilities": caps,
        "risk_level": level,
        "risk_reasons": reasons,
        "errors": errors[:30],
        "warnings": warnings[:30],
    }


def capability_summary(result_or_caps):
    """Return a short, UI-safe Chinese summary of normalized capabilities."""
    if isinstance(result_or_caps, dict) and "capabilities" in result_or_caps:
        caps = result_or_caps.get("capabilities") or {}
        risk = result_or_caps.get("risk_level") or "low"
        legacy = bool(result_or_caps.get("legacy"))
    else:
        caps = result_or_caps or {}
        risk, _ = risk_level(caps)
        legacy = False
    parts = []
    if legacy:
        parts.append("legacy/默认拒绝")
    net = caps.get("network") or {}
    if net.get("enabled"):
        parts.append("网络:" + ",".join(net.get("domains") or []))
    fs = caps.get("filesystem") or {}
    if fs.get("read"):
        parts.append("读文件:%d" % len(fs.get("read") or []))
    if fs.get("write"):
        parts.append("写文件:%d" % len(fs.get("write") or []))
    if (caps.get("process") or {}).get("enabled"):
        parts.append("子进程")
    if (caps.get("ui_control") or {}).get("enabled"):
        parts.append("UI控制")
    if (caps.get("config") or {}).get("read_secrets"):
        parts.append("读取密钥")
    if not parts:
        parts.append("无额外能力")
    return "风险:%s | %s" % (risk, "  ".join(parts))


def _domain_matches(host, allowed):
    host = str(host or "").lower().rstrip(".")
    allowed = str(allowed or "").lower().rstrip(".")
    if allowed.startswith("*."):
        suffix = allowed[1:]
        return host.endswith(suffix) and host != allowed[2:]
    return host == allowed


def _path_allowed(root, path, scopes):
    real_root = os.path.realpath(os.path.abspath(root))
    real_path = os.path.realpath(os.path.abspath(path))
    try:
        if os.path.commonpath([real_root, real_path]) != real_root:
            return False
    except (ValueError, OSError):
        return False
    rel = os.path.relpath(real_path, real_root).replace("\\", "/")
    plugin_name = os.path.basename(real_root)
    project_prefix = "data/plugin_data/%s" % plugin_name
    for scope in scopes or []:
        norm = str(scope or "").replace("\\", "/").strip("/")
        if norm.startswith(project_prefix + "/"):
            norm = norm[len(project_prefix) + 1:]
        elif norm == project_prefix:
            norm = ""
        if norm in ("", ".") or rel == norm or rel.startswith(norm + "/"):
            return True
    return False


def capability_allows(caps, kind, *, domain=None, method="GET", plugin_root=None,
                      path=None, argv=None, key=None):
    """Deterministic runtime check shared by brokers and tests.

    It never trusts an LLM or plugin to self-report authorization. Callers pass
    the normalized capability object and the concrete operation target.
    """
    caps = caps or {}
    if kind == "network":
        net = caps.get("network") or {}
        if not net.get("enabled"):
            return False, "network capability is not enabled"
        if not any(_domain_matches(domain, d) for d in (net.get("domains") or [])):
            return False, "domain is not allowlisted: %s" % domain
        if str(method or "GET").upper() not in set(net.get("methods") or ["GET"]):
            return False, "HTTP method is not allowlisted: %s" % method
        return True, "network capability granted"
    if kind == "filesystem":
        fs = caps.get("filesystem") or {}
        action = "write" if str(method).lower() in ("write", "append", "delete") else "read"
        scopes = fs.get(action) or []
        if not scopes:
            return False, "filesystem %s capability is not enabled" % action
        if not plugin_root or not path:
            return False, "plugin_root and path are required"
        if not _path_allowed(plugin_root, path, scopes):
            return False, "path is outside the declared %s scope" % action
        return True, "filesystem capability granted"
    if kind == "process":
        proc = caps.get("process") or {}
        if not proc.get("enabled"):
            return False, "process capability is not enabled"
        candidate = [str(x) for x in (argv or [])]
        if candidate not in [list(x) for x in (proc.get("allow_argv") or [])]:
            return False, "argv does not exactly match an approved command"
        return True, "process capability granted"
    if kind == "ui_control":
        ok = bool((caps.get("ui_control") or {}).get("enabled"))
        return ok, "ui_control capability granted" if ok else "ui_control capability is not enabled"
    if kind == "config":
        cfg = caps.get("config") or {}
        if not key:
            return False, "config key is required"
        if _SECRET_KEY_RE.search(str(key)) and not cfg.get("read_secrets"):
            return False, "secret config access is not declared"
        if str(key) not in set(cfg.get("public_keys") or []) and not cfg.get("read_secrets"):
            return False, "config key is not public: %s" % key
        return True, "config capability granted"
    return False, "unknown capability kind: %s" % kind

def plugin_manifest_info(meta):
    """UI-ready capability/trust summary for a plugin manifest entry."""
    meta = dict(meta or {})
    try:
        result = validate_capabilities(meta)
        return {
            "capabilities": result.get("capabilities"),
            "capability_summary": capability_summary(result),
            "capability_legacy": bool(result.get("legacy")),
            "risk_level": result.get("risk_level"),
            "publisher": str(meta.get("publisher") or meta.get("author") or "unknown"),
            "signature_status": "signed" if meta.get("signature") else "unsigned",
            "version": str(meta.get("version") or "1.0.0"),
            "trust_tier": ("official" if meta.get("first_party") and meta.get("signature")
                           else "signed" if meta.get("signature") else "unsigned"),
            "api_version": str(meta.get("api_version") or "legacy"),
        }
    except Exception:
        return {"capabilities": None, "capability_summary": "能力信息不可用",
                "capability_legacy": True, "risk_level": "unknown",
                "publisher": "unknown", "signature_status": "unknown",
                "api_version": "legacy"}
