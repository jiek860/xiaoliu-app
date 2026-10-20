# -*- coding: utf-8 -*-
"""让守卫脚本在 GBK 控制台（中文 Windows 默认 cp936）也能打印 ✅

为什么需要这个：
    7 个 check_*.py 里 6 个会在结尾 print ✅ ——
    输出被重定向 / 走进管道时，Python 用系统区域编码（中文 Windows = cp936）
    去编码，直接
        py -3 tools/check_version.py
    会在最后一行崩 UnicodeEncodeError（'gbk' 编不了 ✅）。
    而《工程化落地执行手册》第一节正是这么教用户跑的。
    check.bat 里设了 chcp 65001 + PYTHONIOENCODING，所以走 bat 没事；
    直接跑就崩。这个模块就是补这个洞。

⚠️ 只吞 AttributeError / OSError：
    stdout 被换成非 TextIOWrapper 时 reconfigure 属性可能不存在 ——
    那种情况本来也打不出中文，跳过即可。
    用**具体异常类型**是为了不触发 check_silent 的宽泛捕获计数
    （那个守卫只统计 except Exception / BaseException）。
"""
import sys


def use_utf8_console():
    """把 stdout/stderr 切成 UTF-8，避免 GBK 控制台打 emoji 崩掉"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
