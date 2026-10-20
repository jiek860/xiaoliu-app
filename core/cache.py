# -*- coding: utf-8 -*-
"""P1-20: 持久化缓存层 - LLM响应/搜索/嵌入缓存"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, hashlib, time


class DiskCache:
    """磁盘缓存，自动过期"""
    def __init__(self, base, ttl=3600):
        self.cache_dir = os.path.join(base, "data", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.ttl = ttl  # 缓存有效期，默认1小时
        self.memory_cache = {}

    def _key(self, k):
        return hashlib.md5(str(k).encode(), usedforsecurity=False).hexdigest()

    def get(self, key):
        # 先查内存
        if key in self.memory_cache:
            item = self.memory_cache[key]
            if time.time() - item["t"] < self.ttl:
                return item["v"]
            else:
                del self.memory_cache[key]

        # 查磁盘
        path = os.path.join(self.cache_dir, self._key(key) + ".json")
        if not os.path.exists(path):
            return None
        try:
            item = json.load(open(path, encoding="utf-8"))
            if time.time() - item["t"] > self.ttl:
                os.remove(path)
                return None
            self.memory_cache[key] = item
            return item["v"]
        except Exception:
            return None

    def set(self, key, value):
        item = {"v": value, "t": time.time()}
        self.memory_cache[key] = item
        # 写磁盘
        path = os.path.join(self.cache_dir, self._key(key) + ".json")
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def clear(self):
        """清空缓存"""
        self.memory_cache = {}
        for f in os.listdir(self.cache_dir):
            os.remove(os.path.join(self.cache_dir, f))
