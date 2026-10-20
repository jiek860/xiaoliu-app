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
