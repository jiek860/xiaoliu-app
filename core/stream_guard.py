# -*- coding: utf-8 -*-
"""流式中途卡顿看门狗（第 3 批：深度⑦）。

为什么首字超时不够
------------------
现在的首字超时只覆盖"第一个 token 之前"：本地 25s、云端 60s。但模型吐到
一半突然停住时，``requests`` 的读超时是**每次 read 重新计时**的，只要
服务端偶尔发一行（哪怕空行/心跳），就永远不会超时——界面就一直僵在
"正在输入"，用户只能按 Esc。

这里用后台线程盯"最后一次收到 token 的时间"：超过阈值直接 ``close()``
流响应，把阻塞在 ``iter_lines()`` 的线程叫醒，于是上层能立刻收尾、
返回已收到的内容，并按需要降级到非流式/云端。
"""
from __future__ import annotations

import threading
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_STALL_SEC = 20.0
_POLL_SEC = 0.5


class StreamStallGuard:
    """盯住流响应；中途长时间没有 token 就断流。

    用法::

        guard = StreamStallGuard(20, on_stall=report)
        guard.bind(resp)
        guard.start()
        try:
            for line in resp.iter_lines():
                guard.touch()      # 每收到一行就续命
                ...
        finally:
            guard.stop()
            if guard.stalled:
                ...                # 已收内容照旧可用，只是没吐完
    """

    def __init__(self, seconds=DEFAULT_STALL_SEC, on_stall=None, clock=None):
        try:
            seconds = float(seconds or DEFAULT_STALL_SEC)
        except (TypeError, ValueError):
            seconds = DEFAULT_STALL_SEC
        self.seconds = max(1.0, seconds)
        self.stalled = False
        self._clock = clock or time.time
        self._last = self._clock()
        self._resp = None
        self._on_stall = on_stall
        self._stop = threading.Event()
        self._thread = None

    def bind(self, response):
        """登记要监视的流响应（需要能 close）。"""
        self._resp = response
        self._last = self._clock()
        return self

    def touch(self):
        """收到 token/心跳：续命。"""
        self._last = self._clock()

    def idle_for(self):
        return max(0.0, self._clock() - self._last)

    def check_once(self):
        """同步检查一次（不启线程，方便单测）。返回是否已判定卡顿。"""
        if self.stalled:
            return True
        if self.idle_for() < self.seconds:
            return False
        self._fire()
        return self.stalled

    def _fire(self):
        self.stalled = True
        resp = self._resp
        if resp is not None:
            try:
                resp.close()
            except Exception as e:  # 静默是故意的：关不上也照样判定卡顿
                _x6_swallowed(__name__, e, "close stalled stream")
        if self._on_stall:
            try:
                self._on_stall(self)
            except Exception as e:  # 静默是故意的：回调失败不影响断流
                _x6_swallowed(__name__, e, "stall callback")

    def _run(self):
        while not self._stop.wait(_POLL_SEC):
            if self.check_once():
                return

    def start(self):
        if self._thread is not None:
            return self
        self._last = self._clock()
        self._thread = threading.Thread(target=self._run,
                                        name="StreamStallGuard", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            try:
                thread.join(1.0)
            except Exception as e:  # 静默是故意的：收尾失败不影响主流程
                _x6_swallowed(__name__, e, "join stall guard")
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def guard_seconds(config, default=DEFAULT_STALL_SEC):
    """从配置读卡顿阈值（支持中文键，夹在 5~120 秒）。"""
    from core.llm_shared import config_seconds
    return float(config_seconds(
        config, ("流式卡顿超时", "stream_stall_timeout"), default,
        low=5, high=120))
