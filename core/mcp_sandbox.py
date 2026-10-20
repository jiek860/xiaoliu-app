# -*- coding: utf-8 -*-
"""MCP startup policy, tool risk classification and audit helpers."""
from __future__ import annotations

import hashlib
import os

READ_HINTS = ("read", "list", "get", "search", "query", "fetch", "describe")
WRITE_HINTS = ("write", "edit", "delete", "remove", "move", "copy", "upload",
               "download", "backup", "save", "create")
EXEC_HINTS = ("exec", "execute", "command", "shell", "process", "run",
              "powershell", "cmd")
UI_HINTS = ("ui", "click", "keyboard", "mouse", "window", "screen")


def _perm_strings(tool):
    out = []
    for item in tool.get("permissions") or []:
        if isinstance(item, str):
            out.append(item.lower())
        elif isinstance(item, dict):
            out.extend("%s:%s" % (k, v) for k, v in item.items())
    return out


def classify_tool(tool):
    """Return ``{level, reasons, declared}`` for an MCP tool description.

    Unknown/undeclared tools are treated as high risk so callers that enforce
    this policy can require explicit confirmation or deny them.
    """
    tool = tool or {}
    declared = bool(tool.get("permissions") or tool.get("capability"))
    text = " ".join([
        str(tool.get("name") or ""),
        str(tool.get("description") or tool.get("desc") or ""),
        " ".join(_perm_strings(tool)),
    ]).lower()
    reasons = []
    if any(x in text for x in ("process", "execute:high", "exec", "shell")):
        reasons.append("process/execute")
    if any(x in text for x in ("ui_control", "ui:write", "click", "keyboard")):
        reasons.append("ui_control")
    if any(x in text for x in ("filesystem:write", "write", "delete", "upload")):
        reasons.append("write")
    if any(x in text for x in ("network", "http", "fetch", "download")):
        reasons.append("network")
    if any(x in text for x in ("read", "filesystem:read", "list", "query")):
        reasons.append("read")
    if reasons:
        if any(x in reasons for x in ("process/execute", "ui_control")):
            level = "high"
        elif any(x in reasons for x in ("write", "network")):
            level = "medium"
        else:
            level = "low"
    else:
        level = "unknown"
    return {"level": level, "reasons": reasons, "declared": declared}


def startup_manifest(server):
    server = server or {}
    command = str(server.get("command") or server.get("url") or "")
    env = server.get("env") or {}
    return {
        "name": str(server.get("name") or "mcp"),
        "transport": str(server.get("transport") or "stdio"),
        "command": command[:500],
        "command_sha256": hashlib.sha256(command.encode("utf-8", "replace")).hexdigest()[:16],
        "cwd": str(server.get("cwd") or ""),
        "env_keys": sorted(str(k) for k in env)[:100],
        "risk": ("high" if str(server.get("risk") or "").lower() == "high"
                 else "medium" if server.get("network") else "unknown"),
    }


def should_confirm_startup(server, trust_store=None):
    """Return True unless the exact command hash is in the trust store."""
    manifest = startup_manifest(server)
    trust_store = trust_store or {}
    trusted = set(trust_store.get("trusted_commands") or [])
    return manifest["command_sha256"] not in trusted
