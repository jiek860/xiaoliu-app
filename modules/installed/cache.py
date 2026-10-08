# -*- coding: utf-8 -*-
"""磁盘缓存模块 - 把常用问答存到硬盘，重复问题秒回"""
import os, json, time, threading
from modules.base import BaseModule
from core.safe import atomic_write_json

class DiskCache(BaseModule):
    _max_size = 200  # 最多存200条
    _expire_days = 7  # 缓存7天过期

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.path = os.path.join(self.base, "data", "cache.json")
        self._lock = threading.Lock()
        self._hits = 0  # 命中次数
        self._miss = 0  # 未命中次数
        # 启动时读缓存到内存
        self._data = {}
        self._load()

    def _load(self):
        """从硬盘读缓存到内存"""
        try:
            if os.path.exists(self.path):
                self._data = json.load(open(self.path, encoding="utf-8"))
                # 清掉过期的
                now = time.time()
                expired = [k for k, v in self._data.items() if now - v.get("time", 0) > self._expire_days*86400]
                for k in expired:
                    del self._data[k]
        except Exception:
            self._data = {}

    def _save_async(self):
        """后台异步写硬盘，不阻塞回复"""
        def _write():
            try:
                with self._lock:
                    atomic_write_json(self.path, self._data)
            except Exception as e:
                try: self._log("缓存保存失败: %s" % str(e)[:40])
                except: pass
        threading.Thread(target=_write, daemon=True).start()

    def get(self, question: str):
        """查缓存，命中返回答案，没命中返回None"""
        q = (question or "").strip().lower()
        if not q:
            self._miss += 1
            return None
        with self._lock:
            item = self._data.get(q)
            if not item:
                self._miss += 1
                return None
            # 检查过期
            if time.time() - item.get("time", 0) > self._expire_days*86400:
                del self._data[q]
                self._miss += 1
                return None
            self._hits += 1
            return item["answer"]

    def set(self, question: str, answer: str):
        """存一条问答到缓存"""
        q = (question or "").strip().lower()
        if not q or not answer:
            return
        with self._lock:
            self._data[q] = {
                "answer": answer[:2000],  # 答案最多存2000字，防止太长
                "time": time.time()
            }
            # 超过最大数，删最旧的
            if len(self._data) > self._max_size:
                sorted_keys = sorted(self._data.keys(), key=lambda k: self._data[k]["time"])
                for k in sorted_keys[:len(self._data)-self._max_size]:
                    del self._data[k]
        # 后台写
        self._save_async()

    def clear(self):
        """清空缓存（换模型/新对话的时候调）"""
        with self._lock:
            self._data = {}
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass
        try: self._log("缓存已清空")
        except: pass

    def stats(self):
        """返回缓存统计"""
        total = self._hits + self._miss
        hit_rate = round(self._hits / total * 100, 1) if total > 0 else 0
        size_kb = 0
        if os.path.exists(self.path):
            size_kb = round(os.path.getsize(self.path) / 1024, 1)
        return {
            "缓存条数": len(self._data),
            "命中次数": self._hits,
            "未命中次数": self._miss,
            "命中率": f"{hit_rate}%",
            "占用大小": f"{size_kb}KB"
        }

    def run(self, *args):
        return self.stats()
