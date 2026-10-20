# -*- coding: utf-8 -*-
"""Agent 运行产物保留策略：防止截图、事件和回滚备份无限增长。"""
from __future__ import annotations

import os
import shutil
import threading
import time

_LOCK = threading.RLock()


def _tail_lines(path, max_lines):
    if not os.path.isfile(path) or max_lines <= 0:
        return False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) <= max_lines:
            return False
        tmp = path + ".trim"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-max_lines:])
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def cleanup_agent_runs(base, max_runs=40, max_age_days=7,
                       max_event_lines=5000):
    """清理 data/agent_runs，返回统计信息。"""
    root = os.path.join(str(base), "data", "agent_runs")
    if not os.path.isdir(root):
        return {"ok": True, "removed": [], "trimmed": []}
    now = time.time()
    dirs = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p):
            try:
                dirs.append((os.path.getmtime(p), p))
            except OSError:
                continue
    dirs.sort(reverse=True)
    removed, trimmed = [], []
    keep = []
    for idx, (mtime, p) in enumerate(dirs):
        old = max_age_days > 0 and (now - mtime) > max_age_days * 86400
        if idx >= max_runs or old:
            try:
                shutil.rmtree(p)
                removed.append(os.path.basename(p))
            except OSError:
                pass
        else:
            keep.append(p)
    for p in keep:
        ev = os.path.join(p, "events.jsonl")
        if _tail_lines(ev, max_event_lines):
            trimmed.append(ev)
    p = os.path.join(root, "code_events.jsonl")
    if _tail_lines(p, max_event_lines):
        trimmed.append(p)
    return {"ok": True, "removed": removed, "trimmed": trimmed}


def maybe_cleanup(base, interval_seconds=6 * 3600, **kwargs):
    """按时间节流执行清理；失败不影响主任务。"""
    root = os.path.join(str(base), "data", "agent_runs")
    marker = os.path.join(root, ".last_cleanup")
    now = time.time()
    with _LOCK:
        try:
            if os.path.isfile(marker):
                last = float(open(marker, encoding="utf-8").read().strip() or 0)
                if now - last < interval_seconds:
                    return {"ok": True, "skipped": True}
        except (OSError, ValueError):
            pass
        try:
            os.makedirs(root, exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(str(now))
        except OSError:
            pass
        try:
            return cleanup_agent_runs(base, **kwargs)
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
