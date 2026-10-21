# -*- coding: utf-8 -*-
"""插件审计日志规范（小6插件标准 v2.1 N15）。

规范要求每行一个 JSON 对象，且必须包含：

    ts             ISO-8601 UTC
    plugin         插件名
    version        插件版本
    action         动作（load / call / capability / uninstall / ...）
    capability     涉及能力（network / filesystem / process / ui_control / config）
    allowed        是否允许（bool）
    detail         说明（已脱敏）
    session_id     会话标识

另外：
  * 敏感字段必须脱敏后再写（凭据、令牌、隐私）
  * 保留周期默认 90 天，到期归档/删除
  * 写失败不得阻断主流程，但要计入健康状态
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from core.redaction import redact_mapping

AUDIT_FILE = "plugin_audit.jsonl"
RETENTION_DAYS = 90
REQUIRED_FIELDS = ("ts", "plugin", "version", "action", "capability",
                   "allowed", "detail", "session_id")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class PluginAudit:
    """插件审计写入器（线程安全、失败不抛）。"""

    def __init__(self, base, retention_days=RETENTION_DAYS):
        self.base = os.path.realpath(os.path.abspath(base))
        self.dir = os.path.join(self.base, "data")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, AUDIT_FILE)
        self.retention_days = int(retention_days or RETENTION_DAYS)
        self._lock = threading.RLock()
        self.write_failures = 0
        self.last_error = ""

    def record(self, *, plugin, action, capability="", allowed=True,
               detail="", version="", session_id="", extra=None):
        """写一条审计。返回写入的记录（即使写盘失败也返回，便于调用方断言）。"""
        rec = {
            "ts": utc_now(),
            "plugin": str(plugin or "")[:80],
            "version": str(version or "")[:40],
            "action": str(action or "")[:60],
            "capability": str(capability or "")[:40],
            "allowed": bool(allowed),
            "detail": str(detail or "")[:500],
            "session_id": str(session_id or "")[:64],
        }
        if extra:
            rec["extra"] = {str(k): str(v)[:200] for k, v in list(extra.items())[:20]}
        safe = redact_mapping(rec)
        line = json.dumps(safe, ensure_ascii=False)
        with self._lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as e:
                self.write_failures += 1
                self.last_error = str(e)[:200]
        return safe

    def read(self, limit=500):
        """读取最近 limit 条（用于自检/导出）。坏行跳过。"""
        if not os.path.isfile(self.path):
            return []
        out = []
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return out[-int(limit):]

    def stats(self):
        recs = self.read(limit=100000)
        allowed = sum(1 for r in recs if r.get("allowed"))
        return {"records": len(recs), "allowed": allowed,
                "denied": len(recs) - allowed,
                "write_failures": self.write_failures,
                "last_error": self.last_error,
                "path": self.path}

    def purge_expired(self, now=None):
        """删除超过保留期的记录，返回删除条数。"""
        if not os.path.isfile(self.path):
            return 0
        cutoff = (now or time.time()) - self.retention_days * 86400
        kept, removed = [], 0
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts = _parse_ts(rec.get("ts"))
                    except ValueError:
                        kept.append(line)
                        continue
                    if ts is not None and ts < cutoff:
                        removed += 1
                    else:
                        kept.append(line)
        except OSError:
            return 0
        if removed:
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    for line in kept:
                        f.write(line + "\n")
                os.replace(tmp, self.path)
            except OSError:
                pass
        return removed

    def validate_schema(self, limit=200):
        """检查记录是否包含全部必填字段（供质量门禁使用）。"""
        missing = []
        for rec in self.read(limit):
            lack = [k for k in REQUIRED_FIELDS if k not in rec]
            if lack:
                missing.append({"record": rec.get("ts", "?"), "missing": lack})
        return {"ok": not missing, "checked": min(limit, len(self.read(limit))),
                "missing": missing[:10]}


def _parse_ts(value):
    try:
        text = str(value or "").replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, TypeError):
        return None
