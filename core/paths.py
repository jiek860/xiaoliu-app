# -*- coding: utf-8 -*-
"""统一路径管理 - 消除硬编码，跨平台，兼容打包"""
import os, sys
def get_base():
    """项目根目录"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = get_base()
def data(*parts):
    p = os.path.join(BASE, "data", *parts)
    if parts and "." not in parts[-1]:
        os.makedirs(p, exist_ok=True)
    return p
