# -*- coding: utf-8 -*-
"""界面入口接线测试

为什么要有这个文件
------------------
`_panel_commands()` 里是用 `getattr(self, "xxx", None)` 按**字符串**取方法。
所以 grep "show_tutorial(" 是找不到调用点的 -- 它本来就不是"直接调用"。
这导致过一次误判："show_tutorial 是孤儿 / 全项目无调用"。

这里直接断言"表里有这个键，而且取出来可调用"，比 grep 可靠。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from gui.mixins.dialog_mixin import DialogMixin  # noqa: E402


class _FakeWindow:
    """只提供 _panel_commands 会 getattr 的那几个方法"""
    def show_tutorial(self):
        return "ok"

    def show_feedback(self):
        return "ok"

    def show_components(self):
        return "ok"


def test_tutorial_entry_is_wired():
    d = DialogMixin._panel_commands(_FakeWindow())
    assert "新手教程" in d, "面板表里没有「新手教程」"
    assert callable(d["新手教程"]), "「新手教程」不是可调用对象"


def test_feedback_entry_is_wired():
    d = DialogMixin._panel_commands(_FakeWindow())
    assert "意见反馈" in d, "面板表里没有「意见反馈」"
    assert callable(d["意见反馈"]), "「意见反馈」不是可调用对象"


def test_settings_dialog_renders_both_buttons():
    src = open(os.path.join(BASE, "gui", "settings_dialog.py"),
               encoding="utf-8").read()
    assert '"新手教程"' in src, "设置窗口没有渲染「新手教程」按钮"
    assert '"意见反馈"' in src, "设置窗口没有渲染「意见反馈」按钮"


def test_tutorial_content_is_detailed():
    src = open(os.path.join(BASE, "gui", "tutorial_dialog.py"),
               encoding="utf-8").read()
    for section in ("【一、第一次用", "命令面板 Ctrl+K", "【八、快捷键】"):
        assert section in src, "教程缺少章节: %s" % section


def test_components_entry_is_wired():
    d = DialogMixin._panel_commands(_FakeWindow())
    assert "可选组件" in d, "面板表里没有「可选组件」"
    assert callable(d["可选组件"]), "「可选组件」不是可调用对象"


def test_plugin_dialog_no_longer_has_mcp_or_components_buttons():
    """MCP / 可选组件 已从插件市场移走（MCP 去设置-扩展，可选组件去设置-系统）"""
    src = open(os.path.join(BASE, "gui", "plugin_dialog.py"),
               encoding="utf-8").read()
    assert "mcp_btn" not in src, "插件市场里还残留 MCP 按钮"
    assert "opt_btn" not in src, "插件市场里还残留 可选组件 按钮"


def test_components_dialog_has_deps_and_mirrors():
    src = open(os.path.join(BASE, "gui", "components_dialog.py"),
               encoding="utf-8").read()
    for needle in ("PyQt5", "faster-whisper", "playwright", "opencv-python",
                   "pypi.tuna.tsinghua.edu.cn", "hf-mirror.com",
                   "cdn.npmmirror.com", "一键安装全部未装组件"):
        assert needle in src, "可选组件窗口缺少: %s" % needle
