# -*- coding: utf-8 -*-
"""电脑 Agent 文件操作的备份与回滚存储。"""
from __future__ import annotations

import json
import os
import shutil
import time


class FileRollbackStore:
    def __init__(self, base, run_dir=""):
        self.base = base
        self.run_dir = run_dir or os.path.join(base, "data", "agent_runs")
        self.items = []

    def _backup_path(self, path):
        try:
            if not path or not os.path.isfile(path):
                return ""
            d = os.path.join(self.run_dir, "backups")
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, "%s.%s.bak" % (
                os.path.basename(path), time.time_ns()))
            shutil.copy2(path, dst)
            return dst
        except OSError:
            return ""

    def remember(self, action):
        t = (action or {}).get("type")
        args = (action or {}).get("args") or {}
        target = (action or {}).get("target") or {}
        path = args.get("path") or target.get("path")
        dst = args.get("dst") or args.get("destination") or target.get("dst")
        if t in ("write_file", "edit_file", "delete_file", "copy_file",
                 "move_file"):
            self.items.append({
                "type": t, "path": path, "dst": dst,
                "existed": bool(path and os.path.exists(path)),
                "backup": self._backup_path(path),
                "dst_existed": bool(dst and os.path.exists(dst)),
                "dst_backup": self._backup_path(dst),
            })
        rb = (action or {}).get("rollback") or {}
        if rb.get("type") in ("hotkey", "press_key"):
            self.items.append({
                "type": "ui_rollback", "rollback": rb,
                "reason": (action or {}).get("reason", "")})

    def save(self, run_id):
        if not self.items:
            return ""
        os.makedirs(self.run_dir, exist_ok=True)
        path = os.path.join(self.run_dir, "rollback.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"run_id": run_id, "items": self.items},
                      f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def load(base, run_id):
        path = os.path.join(base, "data", "agent_runs", run_id,
                            "rollback.json")
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("items") or []
        except (OSError, ValueError):
            return []

    @staticmethod
    def rollback(items, controller):
        restored = []
        for item in reversed(items or []):
            try:
                t = item.get("type")
                p = item.get("path")
                d = item.get("dst")
                if t == "write_file" and not item.get("existed") and p and os.path.isfile(p):
                    os.remove(p)
                    restored.append(p)
                elif t == "copy_file" and not item.get("dst_existed") and d and os.path.isfile(d):
                    os.remove(d)
                    restored.append(d)
                elif t == "move_file":
                    if d and os.path.isfile(d):
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        os.replace(d, p)
                        restored.append(p)
                elif t == "ui_rollback":
                    rb = item.get("rollback") or {}
                    if rb.get("type") == "hotkey":
                        controller.hotkey(rb.get("keys") or [])
                    elif rb.get("type") == "press_key":
                        controller.press_key(str(rb.get("key") or ""))
                    restored.append("ui_rollback")
                elif item.get("backup") and os.path.isfile(item["backup"]):
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    shutil.copy2(item["backup"], p)
                    restored.append(p)
                if item.get("dst_backup") and d and os.path.isfile(item["dst_backup"]):
                    shutil.copy2(item["dst_backup"], d)
                    restored.append(d)
            except OSError:
                continue
        return restored
