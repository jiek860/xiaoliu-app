# -*- coding: utf-8 -*-
"""可取消令牌：跨线程通知 + 主动关闭阻塞中的网络资源。

为什么需要它
------------
Qt 的 QThread 无法从外部安全地 `terminate()`。原来的 StreamWorker.stop()
只是把一个 `_is_stopped` 标志置 True，而全项目没有任何地方读它 ——
用户按 Esc 后界面停了，后台的 requests 流仍在读，Ollama 锁也没释放，
下一条消息要么排队，要么提示"上一条还在回复"。

这里用两步让取消真正生效：
  1. `is_cancelled()` 供流循环逐块检查，主动 break；
  2. `bind(closer)` 让发起方登记可关闭的资源（如 stream response），
     `cancel()` 时在**取消线程**里直接 close，把阻塞在 `iter_lines()`
     上的读线程叫醒，从而立刻释放连接与 Ollama 锁。
"""
from __future__ import annotations

import threading

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CancelToken:
    """线程安全的取消令牌。"""

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers = []

    def cancel(self):
        """请求取消：先置位，再关闭所有登记的资源。"""
        self._event.set()
        with self._lock:
            closers = list(self._closers)
            self._closers = []
        for closer in closers:
            try:
                closer()
            except Exception as e:  # 静默是故意的：关闭失败不能影响取消本身
                _x6_swallowed(__name__, e, "cancel closer")

    def is_cancelled(self):
        return self._event.is_set()

    def bind(self, closer):
        """登记一个可关闭资源；若已经取消，立即关闭它。"""
        if not callable(closer):
            return
        with self._lock:
            if self._event.is_set():
                self._closers = []
                late = True
            else:
                self._closers.append(closer)
                late = False
        if late:
            try:
                closer()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "cancel closer (late)")

    def unbind(self, closer):
        """资源正常结束后注销，避免取消时重复 close。"""
        with self._lock:
            try:
                self._closers.remove(closer)
            except ValueError:
                pass
