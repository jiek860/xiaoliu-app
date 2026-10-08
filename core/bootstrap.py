# -*- coding: utf-8 -*-
"""A6: bootstrap - 统一设置sys.path，不用每个模块自己insert"""
import os, sys

def setup():
    """把项目根目录加到sys.path，所有模块import core.xxx都能用"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if base not in sys.path:
        sys.path.insert(0, base)
    return base
