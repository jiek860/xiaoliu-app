# -*- coding: utf-8 -*-
"""集中记录被兜底吞掉的异常，避免真正故障完全静默。"""
from __future__ import annotations

import collections
import threading
import time
import traceback

_LOCK = threading.RLock()
_COUNT = 0
_RECENT: collections.deque = collections.deque(maxlen=500)


def swallowed(component, error, context=""):
    """记录一次被吞掉的异常，但不改变原控制流。"""
    global _COUNT
    with _LOCK:
        _COUNT += 1
        try:
            detail = "".join(traceback.format_exception_only(
                type(error), error)).strip()[:500]
        except Exception:
            detail = str(error)[:500]
        rec = {"time": time.time(), "component": str(component or "")[:120],
               "context": str(context or "")[:300],
               "error": detail, "count": _COUNT}
        _RECENT.append(rec)
    return rec


def recent(limit=100):
    with _LOCK:
        return list(_RECENT)[-max(0, int(limit or 0)):]


def stats():
    with _LOCK:
        return {"total": _COUNT, "recent": len(_RECENT)}
