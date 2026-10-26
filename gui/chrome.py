# -*- coding: utf-8 -*-
"""窗口外框：主区域标签页与状态栏元信息。

左侧活动栏已移除：侧栏本身已有「对话/任务/资料/设置」入口，避免两套导航重复。
图标轨道相关代码不再保留，面板入口统一走侧栏/更多菜单。
"""
from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QTabBar, QTabWidget, QWidget

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def run_modal_once(win, key, opener):
    """模态窗口重入守卫：同一个 key 正在打开时，第二次调用直接忽略。

    模态 exec_() 会禁用主窗，正常情况下点不到第二次；但链接双击、
    快捷键连按、命令面板回车会把两次调用先后排进事件队列，
    第二次数会再建一个窗口叠在上面。
    """
    busy = getattr(win, "_modal_busy", None)
    if busy is None:
        busy = win._modal_busy = set()
    if key in busy:
        return None
    busy.add(key)
    try:
        return opener()
    finally:
        busy.discard(key)


def _front(w, focus=None):
    w.show()
    w.raise_()
    w.activateWindow()
    if focus is not None:
        focus(w)


def singleton_window(win, key, factory, focus=None):
    """非模态窗口单例：已开着就前置；用户关掉/销毁后才允许重建。"""
    cache = getattr(win, "_window_cache", None)
    if cache is None:
        cache = win._window_cache = {}
    w = cache.get(key)
    if w is not None:
        try:
            if w.isVisible():
                _front(w, focus)
                return w
        except RuntimeError:
            pass
        cache.pop(key, None)
        try:
            w.deleteLater()
        except Exception as e:  # 静默是故意的 - 旧对象清理失败不影响新窗口
            _x6_swallowed(__name__, e, "cleanup stale window")
    w = factory()
    if w is None:
        return None
    cache[key] = w
    _front(w, focus)
    return w

def attach_status_meta(win, statusbar):
    """状态栏补充：模型名 + 当日 token 用量。

    运行中任务数、本地/云端指示灯已由 _build_statusbar 建好，这里只补缺的信息。
    用量统计放在 60 秒定时器里刷新，且加了时间戳护栏，
    不会每秒去扫 data/usage 下的 jsonl。
    """
    win.status_model_label = QLabel("模型：—")
    win.status_model_label.setStyleSheet(
        "color:#667085;font-size:11px;padding:0 8px;")
    win.status_token_label = QLabel("token：—")
    win.status_token_label.setStyleSheet(
        "color:#667085;font-size:11px;padding:0 8px;")
    win.status_token_label.setToolTip("今日 token 用量（输入+输出），点「更多 → 用量成本」看明细")
    statusbar.addPermanentWidget(win.status_model_label)
    statusbar.addPermanentWidget(win.status_token_label)

    refresh_status_meta(win)
    timer = QTimer(win)
    timer.timeout.connect(lambda: refresh_status_meta(win))
    timer.start(60000)
    win._status_meta_timer = timer


def _today_tokens(base):
    """读取当日 token 用量；任何异常都退化成 None，不打断界面。"""
    try:
        from core.usage_tracker import UsageTracker
        summary = UsageTracker(base).summary(days=1)
        return int(summary.get("tokens_in") or 0) + int(summary.get("tokens_out") or 0)
    except Exception:  # 静默是故意的
        return None


def refresh_status_meta(win, force=False):
    """刷新模型名和 token 两个状态位；默认 30 秒内不重复统计。"""
    model_label = getattr(win, "status_model_label", None)
    if model_label is not None:
        try:
            mode = win.trunk.config.get("model_mode", "本地路由")
        except Exception:  # 静默是故意的
            mode = "本地路由"
        model_label.setText("模型：%s" % mode)

    token_label = getattr(win, "status_token_label", None)
    if token_label is None:
        return
    now = time.time()
    if not force and now - float(getattr(win, "_status_token_at", 0) or 0) < 30:
        return
    win._status_token_at = now
    base = getattr(win, "base", None)
    if not base:
        token_label.setText("token：—")
        return
    total = _today_tokens(base)
    if total is None:
        token_label.setText("token：—")
    else:
        token_label.setText("token：%s" % _human(total))


def _human(n):
    if n >= 1000000:
        return "%.1fM" % (n / 1000000.0)
    if n >= 1000:
        return "%.1fk" % (n / 1000.0)
    return str(int(n))


def build_main_tabs(win, chat_layout):
    """主区域改成顶部标签页：对话常驻，面板按需以标签页形式打开。"""
    tabs = QTabWidget()
    tabs.setObjectName("mainTabs")
    tabs.setDocumentMode(True)
    tabs.setTabsClosable(True)
    page = QWidget()
    page.setLayout(chat_layout)
    index = tabs.addTab(page, "💬 对话")
    # 对话页不允许关闭，其余面板可以关。
    tabs.tabBar().setTabButton(index, QTabBar.RightSide, None)
    tabs.tabCloseRequested.connect(lambda i: close_panel_at(win, i))
    win.main_tabs = tabs
    win.chat_tab_index = index
    win._panel_tabs = {}
    return tabs


def embed_panel(win, key, title, widget):
    """把已经构造好的对话框挂成标签页；同一个 key 只保留一个实例。"""
    tabs = getattr(win, "main_tabs", None)
    if tabs is None:
        widget.show()
        return widget
    widget.setWindowFlags(Qt.Widget)
    widget.setParent(tabs)
    index = tabs.addTab(widget, title)
    widget._panel_key = key
    win._panel_tabs[key] = widget
    tabs.setCurrentIndex(index)
    return widget


def close_panel_at(win, index):
    """关闭面板标签页；对话页不响应关闭。"""
    tabs = getattr(win, "main_tabs", None)
    if tabs is None or index == getattr(win, "chat_tab_index", 0):
        return
    widget = tabs.widget(index)
    if widget is None:
        return
    key = getattr(widget, "_panel_key", "")
    if key:
        win._panel_tabs.pop(key, None)
    tabs.removeTab(index)
    widget.deleteLater()


def open_panel(win, key, title, module, cls_name):
    """构造面板并挂成标签页；没有标签容器时退回独立窗口（单例）。"""
    tabs = getattr(win, "main_tabs", None)
    if tabs is None:
        return win._singleton_dialog(key, module, cls_name)
    panels = getattr(win, "_panel_tabs", None)
    if panels is None:
        panels = win._panel_tabs = {}
    panel = panels.get(key)
    if panel is not None:
        try:
            tabs.setCurrentWidget(panel)
            return panel
        except RuntimeError:
            # 标签页已关闭，底层对象已销毁，重建
            panels.pop(key, None)
    try:
        import importlib
        cls = getattr(importlib.import_module(module), cls_name)
        widget = cls(win.trunk, None)
    except Exception as e:  # 静默是故意的 - 模块坏了提示而不是崩
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(win, "打开失败", str(e)[:160])
        return None
    return embed_panel(win, key, title, widget)
