# -*- coding: utf-8 -*-
"""LLM 客户端共享锁和模式判断。"""
from __future__ import annotations

import threading

_OLLAMA_LOCK = threading.RLock()


def get_ollama_lock():
    return _OLLAMA_LOCK


def _is_cloud_mode(mode):
    m = str(mode).lower()
    return ("云端" in str(mode)) or ("cloud" in m)


def config_seconds(config, keys, default, low=5, high=300):
    """从配置里读一个"秒"值（支持中文键），并夹在合理区间内。

    用来做首字超时这类可调参数：配置缺失/写错时回到默认值，
    不让一个手误的字符串把流式请求变成瞬时超时。
    """
    config = config or {}
    for key in keys:
        raw = config.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return max(low, min(high, int(float(raw))))
        except (TypeError, ValueError):
            continue
    return default
