# -*- coding: utf-8 -*-
"""结构化安全审计日志。

只记录谁、对什么、做了什么决定、结果如何，不记录完整请求体、Token、
密码或文件正文。日志按大小轮转，写入失败不能影响主流程。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import re
import threading
import time

from core.path_safety import safe_join

_MAX_SIZE = 5 * 1024 * 1024
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.I), r"\1***"),
    (re.compile(r"((?:key|token|secret|passwd|password)=)[^&\s\"']+", re.I), r"\1***"),
    (re.compile(r"(/hook/)[A-Za-z0-9\-]{8,}"), r"\1***"),
]


def redact(text, limit=300):
    s = str(text or "")
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    return s[:limit]


class AuditLog:
    def __init__(self, base):
        self.base = base
        self.dir = os.path.join(base, "data", "security")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "audit.jsonl")
        self._lock = threading.RLock()

    def _rotate(self):
        try:
            if os.path.exists(self.path) and os.path.getsize(self.path) > _MAX_SIZE:
                old = self.path + ".old"
                os.replace(self.path, old)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def append(self, event):
        rec = dict(event or {})
        rec.setdefault("time", time.strftime("%Y-%m-%d %H:%M:%S"))
        for k in ("subject", "task_id", "decision", "result",
                  "reason", "args_preview", "module", "domain", "purpose"):
            if k in rec:
                rec[k] = redact(rec[k], 500)
        with self._lock:
            self._rotate()
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                return True
            except Exception:
                return False

    def list_recent(self, limit=100):
        if not os.path.exists(self.path):
            return []
        try:
            lines = open(self.path, encoding="utf-8").read().splitlines()[-limit:]
            return [json.loads(x) for x in lines if x.strip()]
        except Exception:
            return []

    def export_redacted(self, out_path, limit=1000):
        target = os.path.abspath(out_path)
        recs = self.list_recent(limit=limit)
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"audit": recs}, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": target, "count": len(recs)}
