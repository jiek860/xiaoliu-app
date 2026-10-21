# -*- coding: utf-8 -*-
"""字体自愈：确保 Qt 一定能找到可用于中文的字体。

为什么需要
----------
2026-10-20 实测：装完程序后主界面**全是空白块**，没有文字。
排查结果不是布局问题，而是：

    QFontDatabase().families()  ==  []      # 一个字体都没有

Qt 在这种状态下不会报错，只会**把每个字画成空白**，于是整个界面
看起来像"白屏"。常见诱因：

  · PyQt5 自带 Qt 的 `Qt5/lib/fonts/` 目录不存在（新版 wheel 不再带字体）
  · 精简版 Windows / 服务版 / 某些虚拟机没有注册系统字体
  · 打包后 `QT_QPA_FONTDIR` 指向了空目录

做法
----
1. 先看 Qt 是否已经有字体：有就直接返回，**不做任何多余动作**。
2. 没有的话，从 Windows 系统字体目录挑几个中英文主力字体，
   用 `addApplicationFont()` 注册（只影响本进程，不改系统）。
3. 再设置应用的默认字体，避免控件落到"没有字体"的兜底状态。
4. 全程不抛异常：字体修不好也不能挡住启动。
"""
from __future__ import annotations

import os
import sys

from core.diagnostics import swallowed as _x6_swallowed

# 优先顺序：先中文（界面以中文为主），再英文兜底
_WINDOWS_FONTS = (
    ("msyh.ttc", "Microsoft YaHei UI"),     # 微软雅黑（Win7+）
    ("msyhbd.ttc", "Microsoft YaHei UI"),
    ("simhei.ttf", "SimHei"),
    ("simsun.ttc", "SimSun"),
    ("segoeui.ttf", "Segoe UI"),
    ("segoeuib.ttf", "Segoe UI"),
    ("arial.ttf", "Arial"),
)

_FALLBACK_DIRS = (
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
)


def _font_dirs():
    seen, out = set(), []
    for d in _FALLBACK_DIRS:
        if d and os.path.isdir(d) and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def system_font_files():
    """返回本机可注册的字体文件绝对路径（按优先级排序）。"""
    out = []
    for directory in _font_dirs():
        for name, _family in _WINDOWS_FONTS:
            p = os.path.join(directory, name)
            if os.path.isfile(p) and p not in out:
                out.append(p)
    return out


def ensure_fonts(app=None, min_families=1):
    """确保 Qt 有可用字体；返回结构化结果（永不抛异常）。

    参数
        app             QApplication 实例；不传就用 QApplication.instance()
        min_families    认为"字体够用"的最少族数

    返回
        {"ok": bool, "before": int, "after": int, "loaded": [路径],
         "families": [族名], "reason": str}
    """
    result = {"ok": False, "before": 0, "after": 0, "loaded": [],
              "families": [], "reason": ""}
    try:
        from PyQt5.QtGui import QFont, QFontDatabase
    except Exception as e:  # 没有 Qt（例如 tools/ 里的脚本）不是错误
        result["reason"] = "PyQt5 不可用: %s" % str(e)[:80]
        return result
    if app is None:
        app = _gui_app()
    if app is None:
        result["reason"] = "没有 QApplication，跳过字体修复"
        return result

    try:
        db = QFontDatabase()
        families = list(db.families())
        result["before"] = len(families)
        if len(families) >= int(min_families):
            result.update(ok=True, after=len(families), families=families,
                          reason="系统字体已可用，无需干预")
            return result

        for path in system_font_files():
            try:
                fid = db.addApplicationFont(path)
                if fid >= 0:
                    result["loaded"].append(path)
            except Exception as e:  # 单个字体坏掉就跳过，继续试下一个
                _x6_swallowed(__name__, e, "single-font fallback")

        families = list(db.families())
        result["after"] = len(families)
        result["families"] = families
        if families:
            # 设一个明确的中文优先字体链，避免控件用"无字体"兜底
            preferred = None
            for want in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
                         "Segoe UI", "Arial"):
                if want in families:
                    preferred = want
                    break
            if preferred:
                try:
                    font = QFont(preferred, 10)
                    if app is not None:
                        app.setFont(font)
                    result["reason"] = "已注册系统字体并设置默认字体: " + preferred
                except Exception as e:  # 设置默认字体失败不影响已注册的字体
                    _x6_swallowed(__name__, e, "default-font fallback")
                    result["reason"] = "已注册系统字体: " + preferred
            else:
                result["reason"] = "已注册系统字体（未匹配到首选族）"
            result["ok"] = True
        else:
            result["reason"] = ("系统字体目录里没有可注册的字体；"
                                "界面会显示空白。请安装微软雅黑或改用完整版 Windows。")
        return result
    except Exception as e:
        result["reason"] = "字体自愈失败: %s" % str(e)[:120]
        return result


def _gui_app():
    """拿到 QGuiApplication 实例；没有就返回 None。

    ⚠️ 没有 QApplication 时访问 QFontDatabase **会让进程直接崩**
    （Qt 报 "Must construct a QGuiApplication before accessing QFontDatabase"，
    随后 0xC0000409 硬退出）。所以所有字体查询都必须先过这一关。
    """
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception:
        try:
            from PyQt5.QtGui import QGuiApplication as QApplication
        except Exception:
            return None
    try:
        return QApplication.instance()
    except Exception:
        return None


def status():
    """给"深度自检"用：当前 Qt 能看到多少字体。"""
    if _gui_app() is None:
        return {"ok": False, "count": 0, "families": [],
                "reason": "没有 QApplication（自检在无界面环境下跳过字体检查）"}
    try:
        from PyQt5.QtGui import QFontDatabase
        fams = list(QFontDatabase().families())
        return {"ok": bool(fams), "count": len(fams), "families": fams[:12],
                "font_dirs": _font_dirs(),
                "candidates": system_font_files()[:6],
                "platform": sys.platform}
    except Exception as e:
        return {"ok": False, "count": 0, "error": str(e)[:120]}
