# -*- coding: utf-8 -*-
"""v26-5.3: 内存优化 完整版"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import gc, weakref, threading, time


class MemoryOptimizer:
    """内存优化：GC调优+弱引用+定期清理"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self._weak_modules = weakref.WeakValueDictionary()
        self._history_cache = []
        self._thread = None
        self._cleanup_count = 0
        self._last_cleanup = 0.0

    def tune_gc(self):
        """调优GC参数，减少GC频率"""
        gc.set_threshold(700, 10, 10)
        gc.set_debug(0)
        return {"ok": True, "msg": "GC阈值已调优（700/10/10）"}

    def register_weak(self, name, obj):
        """用弱引用注册模块，允许GC回收"""
        self._weak_modules[name] = obj

    def cleanup(self):
        """手动清理内存"""
        # 清理事件历史，只留最近200条
        if len(self._history_cache) > 200:
            self._history_cache = self._history_cache[-200:]
        # 强制GC
        collected = gc.collect()
        self._cleanup_count = getattr(self, "_cleanup_count", 0) + 1
        self._last_cleanup = time.time()
        return {"ok": True, "回收对象": collected,
                "弱引用模块数": len(self._weak_modules),
                "清理次数": self._cleanup_count}

    def stats(self):
        """清理状态：次数 / 上次时间 / 弱引用数 / 定期线程是否活着"""
        t = getattr(self, "_thread", None)
        return {"清理次数": getattr(self, "_cleanup_count", 0),
                "上次清理": getattr(self, "_last_cleanup", 0.0),
                "弱引用模块数": len(self._weak_modules),
                "历史缓存条数": len(self._history_cache),
                "定期线程存活": bool(t is not None and t.is_alive())}

    def start_periodic(self, interval=1800):
        """启动定期清理线程，每 interval 秒清理一次（重复调用不会多开线程）"""
        t = getattr(self, "_thread", None)
        if t is not None and t.is_alive():
            return {"ok": True, "间隔秒": interval, "状态": "已在运行"}

        def _loop():
            while True:
                time.sleep(interval)
                try:
                    self.cleanup()
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        self._thread = threading.Thread(target=_loop, daemon=True,
                                        name="memory-cleanup")
        self._thread.start()
        return {"ok": True, "间隔秒": interval, "状态": "已启动"}

    def run(self, *a):
        return self.cleanup()
