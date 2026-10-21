# -*- coding: utf-8 -*-
"""插件熔断与资源上限（小6插件标准 v2.1 N13）。

规范要求：
  * 插件崩溃/超时/异常频发不得影响宿主主流程
  * 连续失败达到阈值（默认 5）后熔断，冷却期（默认 60s）内拒绝调用
  * 资源上限：单次调用 30s / 单插件 512MB / 单次写 100MB / 每分钟 60 次网络
  * 超限返回结构化错误 code="resource.limit_exceeded" + 审计

本模块只做**判定**（纯状态机），不执行插件、不开线程，便于单测。
"""
from __future__ import annotations

import threading
import time

from core.plugin_errors import make_error

# 宿主默认上限（可由管理员通过 config 覆盖）
DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 60.0
DEFAULT_CALL_TIMEOUT_MS = 30_000
DEFAULT_MEMORY_MB = 512
DEFAULT_WRITE_BYTES = 100 * 1024 * 1024
DEFAULT_NETWORK_PER_MINUTE = 60


class CircuitBreaker:
    """单插件熔断器（线程安全）。"""

    def __init__(self, failure_threshold=DEFAULT_FAILURE_THRESHOLD,
                 cooldown_seconds=DEFAULT_COOLDOWN_SECONDS, clock=None):
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._failures = 0
        self._opened_at = 0.0
        self._total_failures = 0
        self._total_success = 0
        self._last_error = ""

    def state(self):
        with self._lock:
            if self._opened_at and self._clock() - self._opened_at < self.cooldown_seconds:
                return "open"
            if self._opened_at:
                # 冷却结束，进入半开：允许一次试探
                return "half_open"
            return "closed"

    def allow(self):
        """是否允许本次调用。"""
        return self.state() != "open"

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0
            self._total_success += 1

    def record_failure(self, reason=""):
        with self._lock:
            self._failures += 1
            self._total_failures += 1
            self._last_error = str(reason)[:200]
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
        return self.state()

    def reset(self):
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def stats(self):
        with self._lock:
            return {
                "state": self.state(),
                "failures": self._failures,
                "threshold": self.failure_threshold,
                "cooldown_s": self.cooldown_seconds,
                "total_failures": self._total_failures,
                "total_success": self._total_success,
                "last_error": self._last_error,
                "remaining_s": max(0.0, round(
                    self.cooldown_seconds - (self._clock() - self._opened_at), 1))
                if self._opened_at else 0.0,
            }

    def error(self):
        """熔断中的结构化错误。"""
        st = self.stats()
        return make_error(
            "PLUGIN_CIRCUIT_OPEN",
            "插件连续失败已熔断，请在 %.0f 秒后重试" % st["remaining_s"],
            retryable=True,
            context={"failures": st["failures"],
                     "threshold": st["threshold"],
                     "remaining_s": st["remaining_s"]})


class RateLimiter:
    """滑动窗口限流（默认每分钟 N 次）。"""

    def __init__(self, per_minute=DEFAULT_NETWORK_PER_MINUTE, clock=None):
        self.limit = max(1, int(per_minute))
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._hits = []

    def allow(self):
        now = self._clock()
        with self._lock:
            self._hits = [t for t in self._hits if now - t < 60.0]
            if len(self._hits) >= self.limit:
                return False
            self._hits.append(now)
            return True

    def stats(self):
        now = self._clock()
        with self._lock:
            recent = [t for t in self._hits if now - t < 60.0]
            return {"limit_per_minute": self.limit, "used": len(recent),
                    "remaining": max(0, self.limit - len(recent))}


class PluginLimits:
    """汇总一个插件的资源上限与熔断状态。"""

    def __init__(self, *, failure_threshold=DEFAULT_FAILURE_THRESHOLD,
                 cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
                 call_timeout_ms=DEFAULT_CALL_TIMEOUT_MS,
                 memory_mb=DEFAULT_MEMORY_MB,
                 write_bytes=DEFAULT_WRITE_BYTES,
                 network_per_minute=DEFAULT_NETWORK_PER_MINUTE):
        self.call_timeout_ms = int(call_timeout_ms)
        self.memory_mb = int(memory_mb)
        self.write_bytes = int(write_bytes)
        self.breaker = CircuitBreaker(failure_threshold, cooldown_seconds)
        self.network = RateLimiter(network_per_minute)
        self._lock = threading.RLock()
        self._written = 0

    def check_write(self, nbytes):
        """检查单次写入是否超限；超限返回结构化错误，否则 None。"""
        size = int(nbytes or 0)
        if size > self.write_bytes:
            return make_error(
                "PLUGIN_RESOURCE_EXHAUSTED",
                "单次写入 %d 字节超过上限 %d" % (size, self.write_bytes),
                context={"limit_bytes": self.write_bytes, "requested": size})
        with self._lock:
            if self._written + size > self.write_bytes:
                return make_error(
                    "PLUGIN_RESOURCE_EXHAUSTED",
                    "写入总量超过上限 %d 字节" % self.write_bytes,
                    context={"limit_bytes": self.write_bytes,
                             "used": self._written, "requested": size})
            self._written += size
        return None

    def check_network(self):
        if not self.network.allow():
            return make_error("PLUGIN_RESOURCE_EXHAUSTED",
                              "网络请求超过每分钟上限",
                              retryable=True,
                              context=self.network.stats())
        return None

    def before_call(self):
        """调用前检查；熔断中返回结构化错误。"""
        if not self.breaker.allow():
            return self.breaker.error()
        return None

    def after_call(self, ok, reason=""):
        if ok:
            self.breaker.record_success()
        else:
            self.breaker.record_failure(reason)

    def stats(self):
        return {"breaker": self.breaker.stats(),
                "network": self.network.stats(),
                "limits": {"call_timeout_ms": self.call_timeout_ms,
                           "memory_mb": self.memory_mb,
                           "write_bytes": self.write_bytes}}
