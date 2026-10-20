# -*- coding: utf-8 -*-
"""Plugin versioning, compatibility, trust tier and update selection."""
from __future__ import annotations

import json
import os
import re

from core.plugin_capabilities import capability_summary, validate_capabilities

_SEMVER = re.compile(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")


def version_tuple(value):
    m = _SEMVER.match(str(value or "").strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in m.groups())


def compare_versions(a, b):
    ta, tb = version_tuple(a), version_tuple(b)
    return (ta > tb) - (ta < tb)


def trust_tier(meta):
    meta = meta or {}
    signed = bool(str(meta.get("signature") or "").strip())
    if meta.get("first_party") and signed:
        return "official"
    if signed:
        return "signed"
    return "unsigned"


def host_compatibility(meta, host_version="25.2.23", api_version="1.0"):
    meta = meta or {}
    reasons = []
    if compare_versions(meta.get("min_host_version"), host_version) > 0:
        reasons.append("requires host >= " + str(meta.get("min_host_version")))
    max_host = str(meta.get("max_host_version") or "").strip()
    if max_host and compare_versions(host_version, max_host) > 0:
        reasons.append("requires host <= " + max_host)
    api = str(meta.get("api_version") or "1.0")
    if api != str(api_version):
        reasons.append("plugin API %s != host API %s" % (api, api_version))
    if meta.get("min_api_version"):
        if compare_versions(api, meta.get("min_api_version")) < 0:
            reasons.append("plugin API below minimum")
    return {"ok": not reasons, "reasons": reasons,
            "host_version": host_version, "api_version": api_version}


def manifest_product_info(meta, host_version="25.2.23", api_version="1.0"):
    meta = meta or {}
    cap = validate_capabilities(meta)
    compat = host_compatibility(meta, host_version, api_version)
    return {
        "name": str(meta.get("name") or meta.get("file") or "unknown"),
        "file": str(meta.get("file") or ""),
        "version": str(meta.get("version") or "1.0.0"),
        "trust_tier": trust_tier(meta),
        "compatible": compat["ok"],
        "compatibility_reasons": compat["reasons"],
        "risk_level": cap.get("risk_level"),
        "capability_summary": capability_summary(cap),
        "signature_status": "signed" if meta.get("signature") else "unsigned",
        "publisher": str(meta.get("publisher") or meta.get("author") or "unknown"),
    }


def select_update(current_version, candidates, host_version="25.2.23",
                  api_version="1.0"):
    compatible, blocked = [], []
    current = str(current_version or "0.0.0")
    for meta in candidates or []:
        if not isinstance(meta, dict):
            continue
        if compare_versions(meta.get("version"), current) <= 0:
            continue
        compat = host_compatibility(meta, host_version, api_version)
        row = manifest_product_info(meta, host_version, api_version)
        if compat["ok"]:
            compatible.append(row)
        else:
            blocked.append(row)
    compatible.sort(key=lambda x: version_tuple(x["version"]), reverse=True)
    return {"update_available": bool(compatible),
            "latest": compatible[0] if compatible else None,
            "blocked": blocked}


class InstallLedger:
    """Small atomic ledger for plugin install/update/rollback audit."""

    def __init__(self, base):
        self.path = os.path.join(base, "data", "plugin_ledger.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.records = self._load()

    def _load(self):
        try:
            data = json.load(open(self.path, encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def record(self, name, version, action="install", metadata=None):
        history = list(self.records.get(name) or [])
        history.append({"version": str(version or "1.0.0"),
                        "action": str(action or "install"),
                        "metadata": dict(metadata or {})})
        self.records[name] = history[-50:]
        self._save()
        return self.records[name][-1]

    def history(self, name):
        return list(self.records.get(name) or [])

    def latest(self, name):
        history = self.history(name)
        return history[-1] if history else None
