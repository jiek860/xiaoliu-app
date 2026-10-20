# -*- coding: utf-8 -*-
"""短 TTL 响应缓存。"""
import hashlib
import threading
import time


class ResponseCache:
    def __init__(self, ttl=300, max_items=128):
        self.ttl = ttl
        self.max_items = max_items
        self._data = {}
        self._lock = threading.RLock()

    def key(self, *parts):
        raw = "|".join(str(x) for x in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            ts, value = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.time(), value)
            if len(self._data) > self.max_items:
                for k in sorted(self._data, key=lambda x: self._data[x][0])[:32]:
                    self._data.pop(k, None)

    def clear(self):
        with self._lock:
            self._data.clear()
