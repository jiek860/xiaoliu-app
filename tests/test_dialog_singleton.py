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
    assert "def _singleton_window" in src
    assert "def _run_modal_once" in src
    chrome = open(os.path.join(BASE, "gui", "chrome.py"), encoding="utf-8").read()
    assert "def singleton_window" in chrome
    assert "def run_modal_once" in chrome


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


def test_all_mixin_entries_reuse_or_guard():
    """主窗口所有 _dialog / open_ 入口都要有复用或重入守卫。

    真实问题：以前只查 dialog_mixin，漏掉了任务中心、活动中心这两个
    非模态窗口，连点会各叠一份。这里把 gui/mixins 下全部入口一起查。
    """
    import glob
    allowed = ("_singleton", "_run_modal_once", "_dialog_cache", "_dlg(",
               "exec_()", "open_panel", "_workbench", "_desktop_pet")
    missing = []
    for path in glob.glob(os.path.join(BASE, "gui", "mixins", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not node.name.endswith("_dialog") and not node.name.startswith("open_"):
                continue
            if node.name.startswith("_"):
                continue
            body = ast.unparse(node)
            if any(k in body for k in allowed):
                continue
            if ".show()" in body:
                missing.append("%s:%s" % (os.path.basename(path), node.name))
    assert not missing, "这些入口没有复用/守卫，连点会开多个窗口: %s" % missing


def test_non_modal_window_reuses_instance_and_reopens():
    """非模态窗口：连点复用同一个，关掉后能重建。"""
    from PyQt5.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication([])  # noqa: F841
    from gui.mixins.dialog_mixin import DialogMixin

    # 不建主窗口：这里只验证缓存逻辑本身
    class Holder:
        pass

    holder = Holder()
    made = []

    def factory():
        d = QDialog()
        made.append(d)
        return d

    d1 = DialogMixin._singleton_window(holder, "_test_reuse", factory)
    d2 = DialogMixin._singleton_window(holder, "_test_reuse", factory)
    assert d1 is d2, "连点两次应复用同一个窗口"
    assert len(made) == 1, "工厂被调用了 %d 次" % len(made)
    d1.close()
    app.processEvents()
    d3 = DialogMixin._singleton_window(holder, "_test_reuse", factory)
    assert d3 is not d1, "关闭后应重新创建"
    assert len(made) == 2


def test_high_frequency_buttons_click_twice_open_one_window():
    """高频入口连点两次：命令面板 / 反馈 / 任务中心 / 活动中心 / 系统检测。"""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    os.environ["X6_DISABLE_LOGIN_PROMPT"] = "1"
    from gui.main_window import JarvisWindow

    w = JarvisWindow()
    try:
        w.show()
        app.processEvents()
        for name in ("command_palette", "show_feedback", "open_task_center",
                     "activity_center_dialog", "sys_dialog"):
            fn = getattr(w, name)
            first = fn()
            second = fn()
            assert first is not None, "%s 没打开" % name
            assert second is first, "%s 连点两次开了两个窗口" % name
    finally:
        try:
            w.close()
        except Exception:  # 静默是故意的
            pass


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
