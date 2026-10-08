# -*- coding: utf-8 -*-
"""版本号 - 全局统一管理"""

__version__ = "v25.1.3"
__app_name__ = "小6智能体"
__author__ = "小6"
__build_date__ = "2026-10-08"


def get_version():
    """返回版本号"""
    return __version__


def get_app_name():
    """返回应用名"""
    return __app_name__


def get_full_name():
    """返回完整名称"""
    return "%s %s" % (__app_name__, __version__)

