# -*- coding: utf-8 -*-
"""窗口单例复用测试（修复"连点按钮开出多个窗口"）。"""

import ast
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5.QtWidgets")


def test_singleton_helper_exists():
    """统一复用入口必须存在。"""
    src = open(os.path.join(BASE, "gui", "mixins", "dialog_mixin.py"),
               encoding="utf-8").read()
    assert "def _singleton_dialog" in src
    assert "def _singleton_fn_dialog" in src


def test_mcp_dialog_returns_window():
    """MCP 之前只 .show() 不 return，调用方拿不到窗口对象。"""
    src = open(os.path.join(BASE, "gui", "mixins", "dialog_mixin.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "mcp_dialog":
            body = ast.unparse(node)
            assert "return" in body, "mcp_dialog 必须返回窗口对象"
            # 复用以单例缓存或标签页容器实现，两种都算
            assert any(k in body for k in ("_singleton_dialog", "open_panel")), \
                "mcp_dialog 必须走复用机制"
            return
    pytest.fail("没找到 mcp_dialog")


def test_dialog_functions_use_singleton():
    """所有 _dialog 入口都应走单例，避免重复构造。"""
    src = open(os.path.join(BASE, "gui", "mixins", "dialog_mixin.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.endswith("_dialog") and not node.name.startswith("open_"):
            continue
        if node.name.startswith("_"):
            continue
        body = ast.unparse(node)
        # 复用机制有四种合法写法：
        #   _singleton_dialog / _singleton_fn_dialog / _dialog_cache 手动缓存 /
        #   self._dlg(...) 共用窗口工厂 / exec_() 模态（天然单实例）
        if any(k in body for k in ("_singleton", "_dialog_cache",
                                   "_dlg(", "exec_()")):
            continue
        # 只关心"直接 new 一个窗口再 show"的写法
        if ".show()" in body:
            missing.append(node.name)
    assert not missing, "这些入口没有复用机制，连点会开多个窗口: %s" % missing


def test_mcp_clicking_three_times_opens_one_window():
    """真实点击回归：连点 3 次只能有 1 个 MCP 窗口。"""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow
    from gui.mcp_dialog import MCPDialog

    w = JarvisWindow()
    try:
        w.show()
        app.processEvents()
        before = len(w.findChildren(MCPDialog))
        w.mcp_dialog()
        w.mcp_dialog()
        w.mcp_dialog()
        app.processEvents()
        after = len(w.findChildren(MCPDialog))
        assert after - before <= 1, "连点 3 次开出了 %d 个窗口" % (after - before)
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的 - 清理失败不影响断言结果
            pass


def test_singleton_reopens_after_close():
    """窗口关闭后应能重新打开（不能因为缓存了已销毁对象而失效）。"""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow

    w = JarvisWindow()
    try:
        d1 = w.mcp_dialog()
        assert d1 is not None
        d1.close()
        app.processEvents()
        d2 = w.mcp_dialog()
        assert d2 is not None, "关闭后应能重新打开"
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass
