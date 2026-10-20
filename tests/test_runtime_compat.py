# -*- coding: utf-8 -*-
"""兼容矩阵相关纯函数测试。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.check_runtime_compat import (  # noqa: E402
    SUPPORTED_PYTHON, classify_windows, probe,
)


def test_supported_python_matrix():
    assert (3, 10) in SUPPORTED_PYTHON
    assert (3, 11) in SUPPORTED_PYTHON
    assert (3, 12) in SUPPORTED_PYTHON
    assert (3, 9) not in SUPPORTED_PYTHON
    assert (3, 13) not in SUPPORTED_PYTHON


def test_probe_returns_structured_runtime_info():
    r = probe()
    assert "python" in r and "windows" in r
    assert "missing_required" in r


def test_windows_10_11_and_old_clients():
    assert classify_windows(10, 19045, 1)["release"] == "10"
    assert classify_windows(10, 19045, 1)["supported"] is True
    assert classify_windows(10, 22631, 1)["release"] == "11"
    # Windows 7/8 不能因为不是 Server被误判成 Windows 10
    assert classify_windows(6, 7601, 1)["supported"] is False
    assert classify_windows(6, 9600, 1)["release"] == "unsupported"
    assert classify_windows(10, 20348, 3)["server"] is True
