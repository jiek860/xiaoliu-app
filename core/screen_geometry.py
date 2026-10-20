# -*- coding: utf-8 -*-
"""Windows 虚拟桌面 / DPI 坐标工具。"""
from __future__ import annotations
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def virtual_screen_rect(fallback_size=(1920, 1080)):
    """返回 (left, top, width, height)，覆盖所有显示器。"""
    try:
        import win32api
        left = win32api.GetSystemMetrics(76)
        top = win32api.GetSystemMetrics(77)
        width = win32api.GetSystemMetrics(78)
        height = win32api.GetSystemMetrics(79)
        if width > 0 and height > 0:
            return left, top, width, height
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass
    try:
        w, h = fallback_size
        return 0, 0, int(w or 1920), int(h or 1080)
    except Exception:
        return 0, 0, 1920, 1080


def screen_info(fallback_size=(1920, 1080)):
    left, top, width, height = virtual_screen_rect(fallback_size)
    dpi = 96
    try:
        import ctypes
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:
        dpi = 96
    return {"left": int(left), "top": int(top),
            "width": int(width), "height": int(height),
            "scale": round(float(dpi) / 96.0, 3),
            "multi_monitor": bool(left != 0 or top != 0)}
