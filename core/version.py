# -*- coding: utf-8 -*-
"""版本号 - 全局统一管理

这是**全项目唯一的版本号来源**。发版时只改这里，然后跑
    py -3 tools/check_version.py
确认 CHANGELOG、分发说明、示例等都跟着更新了（那个脚本会逐个列出来）。

历史上这里和 CHANGELOG 长期不一致（CHANGELOG 到 v25.1.5 了，
这里还写着 v25.1.3），原因是发版时只改了 CHANGELOG 忘了改这里。
现在有 check_version.py 兜着，不会再悄悄漂移。
"""

__version__ = "v25.2.6"
__app_name__ = "小6智能体"
__author__ = "小6"
__build_date__ = "2026-10-13"


def get_version():
    """返回版本号"""
    return __version__


def get_app_name():
    """返回应用名"""
    return __app_name__


def get_full_name():
    """返回完整名称"""
    return "%s %s" % (__app_name__, __version__)

