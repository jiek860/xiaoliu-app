# -*- coding: utf-8 -*-
"""窗口外框：左侧活动栏与状态栏元信息。

活动栏用 QListWidget 承载图标项，而不是 QPushButton：
按钮预算已在 check_buttons.py 的 184/184 上限，这里不能再新增按钮创建点。
图标项只做导航，不承载业务状态；显隐统一由 apply_ui_mode() 调用
set_activity_advanced_visible() 控制，避免出现第二套可见性规则。
"""
from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QStyle, QTabBar, QTabWidget, QWidget,
)

# (key, 标准图标, 提示, 是否只在高级模式显示)
#
# 这里刻意不用 emoji：Qt5 在 Windows 下对彩色 emoji 字体支持不稳定，
# 实测离屏渲染整条轨道是空白的（图标全丢）。QStyle 的标准图标由系统主题
# 提供，任何环境下都画得出来。
ACTIVITY_ITEMS = (
    ("chat", QStyle.SP_MessageBoxInformation, "对话", False),
    ("task", QStyle.SP_DialogApplyButton, "任务", False),
    ("resources", QStyle.SP_DirIcon, "资料", False),
    ("memory", QStyle.SP_FileDialogDetailedView, "记忆", True),
    ("mcp", QStyle.SP_DriveNetIcon, "MCP", True),
    ("skills", QStyle.SP_FileDialogListView, "技能", True),
    ("settings", QStyle.SP_FileDialogInfoView, "设置", False),
)

_RAIL_STYLE = (
    "QListWidget#activityBar{background:#f7f8fa;border:none;"
    "border-right:1px solid #e0e0e0;outline:none;}"
    "QListWidget#activityBar::item{height:42px;border-radius:8px;"
    "margin:2px 4px;}"
    "QListWidget#activityBar::item:hover{background:#eaf1ff;}"
    "QListWidget#activityBar::item:selected{background:#e3f2fd;}"
)


def build_activity_bar(win):
    """构建窄图标轨道。点击后走 _on_activity_clicked，行为与菜单入口一致。"""
    bar = QListWidget()
    bar.setObjectName("activityBar")
    bar.setFixedWidth(56)
    bar.setIconSize(QSize(22, 22))
    bar.setStyleSheet(_RAIL_STYLE)
    bar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    bar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    style = bar.style()
    for key, std_icon, tip, advanced in ACTIVITY_ITEMS:
        item = QListWidgetItem(style.standardIcon(std_icon), "")
        item.setToolTip(tip)
        item.setData(Qt.UserRole, key)
        item.setData(Qt.UserRole + 1, advanced)
        bar.addItem(item)
    bar.itemClicked.connect(win._on_activity_clicked)
    win.activity_bar = bar
    return bar


def set_activity_advanced_visible(win, visible):
    """简单模式只保留 对话/任务/资料/设置，其余整行隐藏。"""
    bar = getattr(win, "activity_bar", None)
    if bar is None:
        return
    for row in range(bar.count()):
        item = bar.item(row)
        if item is not None and bool(item.data(Qt.UserRole + 1)):
            bar.setRowHidden(row, not visible)


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
