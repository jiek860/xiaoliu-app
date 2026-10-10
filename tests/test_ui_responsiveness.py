# -*- coding: utf-8 -*-
"""界面响应性回归：点功能按钮到窗口出来，不能卡

为什么要这条测试
----------------
功能中心 / 设置里的按钮曾经点一下要等好几秒窗口才出来，原因是
**在 UI 线程上做了阻塞操作**：

    · MCP 面板：打开时同步加载 mcp_client，它会串行起 4 个 stdio 子进程
      （npx / uvx）再握手 —— 实测 10 秒，全压在 UI 线程上
    · 插件市场：打开时同步 pm.list_online() 去仓库拉清单 —— 约 0.9 秒
    · 设置 / 首次设置向导：**构建对话框的过程中**直接请求 Ollama
      （timeout=3）—— 那台机器不在线时每次都要先卡满 3 秒

修法都是"本地/配置先渲染，耗时的部分丢后台线程，好了再发信号回来刷新"。
这里把"打开要快"钉住，避免以后又有人在 UI 线程上写同步 IO。

阈值给得宽松（1.5 秒），只拦"明显卡顿"，不追求精确计时 ——
不同机器、不同负载下差个零点几秒很正常。
"""
import os
import sys
import time
import unittest.mock as mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout,  # noqa: E402
                             QMessageBox, QWizard)

THRESHOLD = 1.5          # 秒；超过就算"点了明显卡"

_app = None
_keep = []


class _NoExecDialog(QDialog):
    def exec_(self):
        return 0


def _fake_dlg(title, w=800, h=600):
    d = _NoExecDialog()
    d.setWindowTitle(title)
    lay = QVBoxLayout(d)
    _keep.append(d)
    return d, lay


@pytest.fixture(scope="module")
def win():
    global _app
    _app = QApplication.instance() or QApplication([])
    # 弹窗一律吞掉，别让测试卡在模态上
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.critical = staticmethod(lambda *a, **k: None)
    QWizard.exec_ = lambda self: 0        # 向导自己会 exec_()，一并桩掉

    from core.trunk import Trunk
    with mock.patch.object(Trunk, "_start_background", lambda self: None), \
         mock.patch.object(Trunk, "_auto_backup", lambda self: None), \
         mock.patch.object(Trunk, "_warmup", lambda self: None), \
         mock.patch.object(Trunk, "_auto_unload_loop", lambda self: None), \
         mock.patch.object(Trunk, "_warmup_ollama", lambda self: None):
        from gui.main_window import JarvisWindow
        w = JarvisWindow()
    w._dlg = _fake_dlg
    return w


def _timeit(fn):
    t = time.time()
    fn()
    return time.time() - t


DIALOGS = [
    ("设置", "set_dialog"),
    ("电脑控制", "computer_dialog"),
    ("系统", "sys_dialog"),
    ("插件", "plugin_dialog"),
    ("日志", "log_dialog"),
    ("MCP", "mcp_dialog"),
    ("机器人", "bot_dialog"),
    ("历史记录", "history_dialog"),
    ("首次设置向导", "onboarding_dialog"),
]


@pytest.mark.parametrize("label,method", DIALOGS)
def test_dialog_opens_quickly(win, label, method):
    fn = getattr(win, method, None)
    if fn is None:
        pytest.skip("主窗口没有 %s" % method)
    dt = _timeit(fn)
    assert dt < THRESHOLD, (
        "%s 打开用了 %.2fs（阈值 %.1fs）—— 检查是不是又在 UI 线程上"
        "做了同步 IO：网络请求 / _load_lazy 加载重模块 / 起子进程"
        % (label, dt, THRESHOLD))


def test_mcp_dialog_does_not_connect_synchronously(win):
    """MCP 面板打开时不能同步去连服务器

    这条以前要 10 秒：打开面板 -> _load_lazy("mcp_client") ->
    串行起 4 个 stdio 子进程 + 握手，全在 UI 线程上。
    现在客户端是后台加载的，面板先用 config 渲染。
    """
    # 先把客户端从 modules 里摘掉，模拟"还没加载过"的首次打开
    saved = win.trunk.modules.pop("mcp_client", None)
    try:
        dt = _timeit(lambda: win.mcp_dialog())
        assert dt < THRESHOLD, "MCP 面板打开用了 %.2fs，客户端八成又被同步加载了" % dt
    finally:
        if saved is not None:
            win.trunk.modules["mcp_client"] = saved


def test_settings_opens_fast_even_if_ollama_unreachable(win):
    """Ollama 连不上时，设置窗口也要立刻出来（探测走后台）

    原来是在构建对话框的过程中直接 urlopen(timeout=3)，
    黑洞地址下每次点设置都要先卡满 3 秒。
    """
    real = win.trunk.config.get("ollama_url")
    win.trunk.config["ollama_url"] = "http://10.255.255.1:11434"
    try:
        dt = _timeit(lambda: win.set_dialog())
        assert dt < THRESHOLD, (
            "Ollama 不可达时设置窗口用了 %.2fs —— 探测又在 UI 线程上同步做了" % dt)
    finally:
        win.trunk.config["ollama_url"] = real


def test_plugin_dialog_renders_without_network(win):
    """插件市场打开时不该等网络：本地那份先画出来"""
    dt = _timeit(lambda: win.plugin_dialog())
    assert dt < THRESHOLD, (
        "插件市场打开用了 %.2fs —— 是不是又同步去 list_online() 了" % dt)
