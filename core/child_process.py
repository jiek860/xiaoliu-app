# -*- coding: utf-8 -*-
"""Child-process environment and working-directory policy.

Used by MCP servers and isolated plugin workers. The rule is allow-list, not
deny-list: a child never inherits the application's full environment.
"""
from __future__ import annotations

import os

from core.path_safety import safe_name

_ALLOWED_ENV_KEYS = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "LANG", "LC_ALL", "LC_CTYPE", "PYTHONIOENCODING", "PYTHONUTF8",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "USERNAME",
    "SYSTEMDRIVE", "DRIVERDATA",
}

_DENIED_CWD_NAMES = {"windows", "system32", "syswow64", "program files",
                     "program files (x86)", "users"}


def minimal_child_env(extra=None):
    env = {}
    for key, value in os.environ.items():
        if key.upper() in _ALLOWED_ENV_KEYS and value is not None:
            env[key] = value
    # Keep the child deterministic and UTF-8 for JSON-RPC.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["X6_CHILD_SANDBOX"] = "1"
    for key, value in (extra or {}).items():
        text = str(key or "")
        if not text or any(x in text.upper() for x in
                           ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD",
                            "CREDENTIAL", "AUTH")):
            continue
        env[text] = str(value)
    return env


def _is_under(root, path):
    try:
        root = os.path.realpath(os.path.abspath(root))
        path = os.path.realpath(os.path.abspath(path))
        return os.path.commonpath([root, path]) == root
    except (TypeError, ValueError, OSError):
        return False


def sandbox_cwd(base, server_name, configured=None):
    """Return a validated child cwd.

    Default: ``<base>/data/mcp/<safe_name>/``. A custom cwd must already exist
    or be creatable under that same root. Project root, user home and system
    directories are rejected even if configured.
    """
    base = os.path.realpath(os.path.abspath(base or "."))
    root = os.path.join(base, "data", "mcp", safe_name(server_name, "server"))
    os.makedirs(root, exist_ok=True)
    if configured:
        candidate = os.path.realpath(os.path.abspath(str(configured)))
        if not _is_under(root, candidate):
            raise ValueError("MCP cwd must stay under %s" % root)
        if candidate == base:
            raise ValueError("MCP cwd may not be the project root")
        if not os.path.isdir(candidate):
            raise ValueError("MCP cwd does not exist: %s" % candidate)
        return candidate
    return root


def validate_cwd(base, server_name, configured=None):
    try:
        return sandbox_cwd(base, server_name, configured)
    except ValueError:
        return None


def env_summary(env):
    """Return keys only; values may contain machine-specific paths or identity."""
    keys = sorted(str(k) for k in (env or {}))
    return {"count": len(keys), "keys": keys}
