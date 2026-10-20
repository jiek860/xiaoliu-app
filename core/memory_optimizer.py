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
        return {"ok": True, "回收对象": collected, "弱引用模块数": len(self._weak_modules)}

    def start_periodic(self, interval=1800):
        """启动定期清理线程，每30分钟清理一次"""
        def _loop():
            while True:
                time.sleep(interval)
                try:
                    self.cleanup()
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        threading.Thread(target=_loop, daemon=True, name="memory-cleanup").start()
        return {"ok": True, "间隔秒": interval, "状态": "已启动"}

    def run(self, *a):
        return self.cleanup()
