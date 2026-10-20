# -*- coding: utf-8 -*-
"""Tool-side policy for prompt-injection defense.

The model's tool choice is probabilistic. This module makes the execution
layer deterministic: an untrusted provenance can never directly authorize a
side effect, and argument paths/URLs are checked before dispatch.
"""
from __future__ import annotations

import json
import os

from core.path_safety import is_sensitive_path
from core.safe_http import validate_http_url

READONLY_RISKS = {"read", "network_read", "mcp_read"}
SIDE_EFFECT_RISKS = {"write", "exec", "ui_control", "ui_network",
                     "read_sensitive", "network", "mcp_external"}


def is_readonly(info):
    info = info or {}
    return bool(info.get("readonly") or
                (info.get("risk") in READONLY_RISKS and
                 not info.get("confirm") and not info.get("danger")))


def side_effect_level(info):
    info = info or {}
    risk = str(info.get("risk") or "").lower()
    if info.get("danger") or risk in ("exec", "write", "ui_control",
                                      "ui_network", "mcp_external"):
        return "high"
    if risk in ("network", "read_sensitive") or info.get("confirm"):
        return "medium"
    return "none"


def requires_confirmation(info, provenance=None):
    if provenance is not None and getattr(provenance, "untrusted", False):
        return not is_readonly(info)
    return side_effect_level(info) in ("medium", "high")


def untrusted_can_execute(info):
    return is_readonly(info)


def _walk_args(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_args(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_args(v, key)
    elif isinstance(obj, str):
        yield key, obj


def validate_args_safety(args, base=None):
    """Return ``(ok, reason)`` before a tool receives user/model arguments."""
    for key, value in _walk_args(args or {}):
        low_key = key.lower()
        if low_key in ("path", "file", "filename", "src", "dst", "workdir",
                       "cwd", "directory"):
            if is_sensitive_path(value, base=base):
                return False, "敏感路径被拒绝: %s" % value[:120]
        if low_key == "spec" and value.strip().startswith("{"):
            try:
                obj = json.loads(value)
            except Exception:
                return False, "spec 不是合法 JSON"
            ok, why = validate_args_safety(obj, base=base)
            if not ok:
                return False, why
        if "://" in value:
            if not validate_http_url(value):
                return False, "只允许 http/https URL: %s" % value[:120]
        if low_key in ("cmd", "command", "shell") and any(
                x in value for x in ("&&", "||", "|", ";", ">", "<", "`",
                                     "$(", "%(", "\n", "\r")):
            return False, "命令包含不允许的 shell 元字符"
    return True, ""


def policy_decision(info, provenance=None, args=None, base=None):
    ok, why = validate_args_safety(args or {}, base=base)
    if not ok:
        return {"allow": False, "requires_confirm": False, "reason": why}
    if provenance is not None and getattr(provenance, "untrusted", False):
        if not untrusted_can_execute(info):
            return {"allow": False, "requires_confirm": False,
                    "reason": "外部内容不能直接触发有副作用的工具"}
        return {"allow": True, "requires_confirm": False,
                "reason": "外部内容只能触发只读工具"}
    if requires_confirmation(info, provenance):
        return {"allow": False, "requires_confirm": True,
                "reason": "工具需要用户确认"}
    return {"allow": True, "requires_confirm": False, "reason": "只读工具"}
