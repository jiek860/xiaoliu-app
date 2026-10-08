# -*- coding: utf-8 -*-
"""事件总线：引擎发事件，GUI订阅"""
import threading

class EventBus:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self, pattern, fn):
        with self._lock:
            self._subs.append((pattern, fn))

    def emit(self, kind, data):
        with self._lock:
            subs = list(self._subs)
        for pattern, fn in subs:
            if pattern == "*" or pattern == kind:
                try: fn(kind, data)
                except: pass
