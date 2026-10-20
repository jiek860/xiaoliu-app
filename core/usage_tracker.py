# -*- coding: utf-8 -*-
"""本地用量统计：模型、工具、token、耗时、费用。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import threading
import time


class UsageTracker:
    def __init__(self, base):
        self.base = base
        self.dir = os.path.join(base, "data", "usage")
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self):
        return os.path.join(self.dir, time.strftime("%Y%m%d") + ".jsonl")

    def record(self, *, kind, name="", model="", tokens_in=0,
               tokens_out=0, cost=0.0, elapsed=0.0, task_id="",
               success=True):
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "_ts": time.time(), "kind": kind, "name": name, "model": model,
               "tokens_in": int(tokens_in or 0),
               "tokens_out": int(tokens_out or 0),
               "cost": float(cost or 0), "elapsed": float(elapsed or 0),
               "task_id": task_id, "success": bool(success)}
        with self._lock:
            try:
                with open(self._path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return rec

    @staticmethod
    def _pct(values, p):
        if not values:
            return 0.0
        values = sorted(float(x) for x in values)
        i = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
        return round(values[i], 3)

    def model_stats(self, model=None, days=7):
        cutoff = time.time() - days * 86400
        rows = []
        for f in os.listdir(self.dir):
            if not f.endswith(".jsonl"):
                continue
            for ln in open(os.path.join(self.dir, f), encoding="utf-8"):
                try:
                    r = json.loads(ln)
                except Exception:  # 静默是故意的 - 单行损坏不影响统计
                    continue
                if float(r.get("_ts") or 0) and float(r["_ts"]) < cutoff:
                    continue
                if model and r.get("model") != model:
                    continue
                rows.append(r)
        by = {}
        for r in rows:
            m = r.get("model") or "unknown"
            b = by.setdefault(m, {"calls": 0, "ok": 0, "fail": 0,
                                  "latencies": [], "tokens": 0, "cost": 0.0})
            b["calls"] += 1
            if r.get("success", True):
                b["ok"] += 1
            else:
                b["fail"] += 1
            b["latencies"].append(float(r.get("elapsed") or 0))
            b["tokens"] += int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0)
            b["cost"] += float(r.get("cost") or 0)
        for b in by.values():
            b["p50"] = self._pct(b["latencies"], 50)
            b["p95"] = self._pct(b["latencies"], 95)
            b.pop("latencies", None)
        if model:
            return by.get(model, {"calls": 0, "ok": 0, "fail": 0,
                                  "p50": 0, "p95": 0, "tokens": 0, "cost": 0.0})
        return by

    def summary(self, days=7):
        cutoff = time.time() - days * 86400
        out = {"calls": 0, "tokens_in": 0, "tokens_out": 0,
               "cost": 0.0, "elapsed": 0.0, "by_model": {}}
        for f in os.listdir(self.dir):
            if not f.endswith(".jsonl"):
                continue
            for ln in open(os.path.join(self.dir, f), encoding="utf-8"):
                try:
                    r = json.loads(ln)
                except Exception:  # 静默是故意的 - 单行损坏不影响统计
                    continue
                if float(r.get("_ts") or 0) and float(r["_ts"]) < cutoff:
                    continue
                out["calls"] += 1
                out["tokens_in"] += int(r.get("tokens_in") or 0)
                out["tokens_out"] += int(r.get("tokens_out") or 0)
                out["cost"] += float(r.get("cost") or 0)
                out["elapsed"] += float(r.get("elapsed") or 0)
                m = r.get("model") or "unknown"
                bm = out["by_model"].setdefault(
                    m, {"calls": 0, "tokens": 0, "cost": 0.0})
                bm["calls"] += 1
                bm["tokens"] += int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0)
                bm["cost"] += float(r.get("cost") or 0)
        return out
