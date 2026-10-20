# -*- coding: utf-8 -*-
"""本地 trace：任务/模型/工具/网络事件时间线。默认只存预览，不存正文。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import threading
import time

from core.audit_log import redact


class Trace:
    def __init__(self, base):
        self.base = base
        self.dir = os.path.join(base, "data", "traces")
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, task_id=None):
        day = time.strftime("%Y%m%d")
        return os.path.join(self.dir, "%s.jsonl" % day)

    def record(self, event):
        rec = dict(event or {})
        rec.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S"))
        rec.setdefault("ts", time.time())
        for k in ("detail", "result_preview", "args_preview", "error"):
            if k in rec:
                rec[k] = redact(rec[k], 500)
        with self._lock:
            try:
                with open(self._path(rec.get("task_id")), "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return True
            except Exception:
                return False

    def read(self, limit=200):
        paths = sorted(
            [os.path.join(self.dir, f) for f in os.listdir(self.dir)
             if f.endswith(".jsonl")])[-3:]
        out = []
        for p in paths:
            try:
                out.extend(json.loads(x) for x in
                           open(p, encoding="utf-8").read().splitlines()
                           if x.strip())
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
        return out[-limit:]
