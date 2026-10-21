# -*- coding: utf-8 -*-
"""Restricted SDK surface for isolated plugin workers.

This is not a Python security sandbox by itself. It is the broker-facing SDK
used by a separate worker process, with a guarded import table and no raw file,
network, process or config access. The actual authorization happens in the
main-process PluginBroker and PermissionCenter.

Any release that allows untrusted third-party plugins still needs OS-level
process isolation and code review; this module exists to make the default SDK
small and auditable.
"""
from __future__ import annotations

import builtins
import json


PLUGIN_ALLOWED_IMPORTS = {
    "json", "re", "time", "datetime", "math", "collections", "typing",
    "dataclasses", "functools", "itertools", "statistics", "decimal",
    "modules.base", "core.plugin_sdk", "core.safe", "core.path_safety",
    "core.tool_schema", "core.error_text",
}

FORBIDDEN_BUILTINS = {
    "open", "exec", "eval", "compile", "input", "breakpoint", "help",
    "exit", "quit", "memoryview",
}


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = str(name or "").split(".", 1)[0]
    allowed = any(str(name or "") == x or str(name or "").startswith(x + ".")
                  for x in PLUGIN_ALLOWED_IMPORTS)
    if not allowed or root in {
            "os", "sys", "subprocess", "socket", "pathlib", "shutil",
            "ctypes", "importlib", "builtins", "urllib", "http", "requests",
            "winreg", "pickle", "marshal", "pty", "multiprocessing"}:
        raise ImportError("plugin import is not allowed: %s" % name)
    return builtins.__import__(name, globals, locals, fromlist, level)


def restricted_builtins():
    safe = dict(vars(builtins))
    for name in FORBIDDEN_BUILTINS:
        safe.pop(name, None)
    safe["__import__"] = _guarded_import
    return safe


class _RpcProxy:
    def __init__(self, rpc):
        self._rpc = rpc

    def _call(self, method, **params):
        return self._rpc(method, params)


class _Files(_RpcProxy):
    def read(self, path, max_bytes=65536):
        return self._call("files.read", path=path, max_bytes=max_bytes)

    def write(self, path, text, append=False):
        return self._call("files.write", path=path, text=text, append=append)


class _Network(_RpcProxy):
    def request(self, url, method="GET", headers=None, body=None, timeout=10):
        return self._call("network.request", url=url, method=method,
                          headers=headers or {}, body=body, timeout=timeout)


class _Process(_RpcProxy):
    def run(self, argv, timeout=15):
        return self._call("process.run", argv=list(argv or []), timeout=timeout)


class _Config(_RpcProxy):
    def get_secret(self, name):
        """读取已声明的凭据（需 capabilities.config.read_secrets）。

        v2.1 S3/S7：凭据只能经 broker 代理读取，不会落插件持久化层。
        """
        return self._call("config.get_secret", {"name": str(name)})

    def get_public(self, key):
        return self._call("config.get_public", key=key)


class _Audit(_RpcProxy):
    def record(self, event):
        return self._call("audit.record", event=str(event)[:500])


class PluginContext:
    def __init__(self, rpc):
        self.files = _Files(rpc)
        self.network = _Network(rpc)
        self.process = _Process(rpc)
        self.config = _Config(rpc)
        self.audit = _Audit(rpc)


def load_plugin_class(source, path, rpc):
    """Load a plugin with restricted imports and return its class + context."""
    globals_dict = {
        "__name__": "x6_isolated_plugin",
        "__file__": str(path),
        "__builtins__": restricted_builtins(),
    }
    code = compile(source, str(path), "exec")
    exec(code, globals_dict)  # nosec B102
    classes = [
        obj for obj in globals_dict.values()
        if isinstance(obj, type) and obj.__module__ == "x6_isolated_plugin"
    ]
    for cls in classes:
        if callable(getattr(cls, "run", None)):
            return cls, PluginContext(rpc)
    raise RuntimeError("plugin contains no class with run()")
