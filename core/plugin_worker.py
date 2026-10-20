# -*- coding: utf-8 -*-
"""Isolated plugin worker.

Protocol: one JSON object per line on stdin/stdout. The worker is intentionally
small; plugin code receives only the restricted PluginContext and guarded
imports from core.plugin_sdk. The main process brokers every sensitive action.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.plugin_sdk import load_plugin_class  # noqa: E402

_PROTO_OUT = sys.stdout
_PROTO_IN = sys.stdin
_IO_LOCK = threading.RLock()
_RPC_ID = 0


def _send(payload):
    with _IO_LOCK:
        _PROTO_OUT.write(json.dumps(payload, ensure_ascii=False) + "\n")
        _PROTO_OUT.flush()


def _rpc(method, params):
    global _RPC_ID
    with _IO_LOCK:
        _RPC_ID += 1
        rid = "p%d" % _RPC_ID
        _send({"jsonrpc": "2.0", "id": rid, "method": method,
               "params": params or {}})
        line = _PROTO_IN.readline()
    if not line:
        raise RuntimeError("broker closed the connection")
    msg = json.loads(line)
    if "error" in msg:
        err = msg.get("error")
        raise PermissionError(str(err.get("message") if isinstance(err, dict) else err))
    return msg.get("result")


def _invoke(plugin_path, args):
    with open(plugin_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    cls, ctx = load_plugin_class(source, plugin_path, _rpc)
    plugin = cls()
    run = plugin.run
    try:
        import inspect
        sig = inspect.signature(run)
        accepts_ctx = len(sig.parameters) > 0
    except Exception:
        accepts_ctx = False
    # Plugin prints must never corrupt the JSON-RPC stream.
    with contextlib.redirect_stdout(sys.stderr):
        result = run(ctx) if accepts_ctx else run()
    if result is None or isinstance(result, (str, int, float, bool, list, dict)):
        return result
    return str(result)


def main():
    if len(sys.argv) < 2:
        _send({"jsonrpc": "2.0", "id": "startup", "error":
               {"message": "plugin path argument is required"}})
        return 2
    plugin_path = os.path.abspath(sys.argv[1])
    for line in _PROTO_IN:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:  # 静默是故意的
            continue
        method = msg.get("method")
        rid = msg.get("id")
        if method != "plugin.run":
            if rid is not None:
                _send({"jsonrpc": "2.0", "id": rid,
                       "error": {"message": "unknown method: %s" % method}})
            continue
        try:
            result = _invoke(plugin_path, (msg.get("params") or {}).get("args") or [])
            _send({"jsonrpc": "2.0", "id": rid, "result": result})
        except Exception as exc:
            _send({"jsonrpc": "2.0", "id": rid,
                   "error": {"message": str(exc)[:300],
                             "type": type(exc).__name__}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
