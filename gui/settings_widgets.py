# -*- coding: utf-8 -*-
"""设置窗口公共小组件。"""
from __future__ import annotations

from PyQt5.QtWidgets import (QLabel, QWidget, QVBoxLayout,
                             QScrollArea, QMessageBox, QListWidget)

from gui.feedback_states import make_action_links


def make_category_nav(tabs, width=136):
    """设置页左侧分类栏：条目取 tabText，与页面索引双向同步。"""
    nav = QListWidget()
    nav.setObjectName("settingsCategory")
    nav.setFixedWidth(width)
    nav.setStyleSheet(
        "QListWidget#settingsCategory{background:#f7f8fa;border:none;"
        "border-right:1px solid #e0e0e0;outline:none;font-size:13px;}"
        "QListWidget#settingsCategory::item{padding:9px 12px;border-radius:8px;"
        "margin:2px 6px;}"
        "QListWidget#settingsCategory::item:hover{background:#eaf1ff;}"
        "QListWidget#settingsCategory::item:selected{background:#e3f2fd;"
        "color:#1976d2;}")
    for i in range(tabs.count()):
        nav.addItem(tabs.tabText(i).strip())
    nav.currentRowChanged.connect(tabs.setCurrentIndex)
    tabs.currentChanged.connect(
        lambda i: nav.setCurrentRow(i) if nav.currentRow() != i else None)
    nav.setCurrentRow(0)
    return nav


def make_open_link(dialog, commands, icon, name, desc, key=None):
    """设置页里的低频入口：用链接而不是按钮。

    以前这里是 QPushButton，设置页 25 个入口就是 25 个全宽按钮 ——
    一屏全是按钮，用户根本不知道该点哪个。链接表达能力一样，
    还能把按钮预算留给真正的主操作。
    """
    want = key if key is not None else name
    fn = commands.get(want)
    if not callable(fn):
        lab = QLabel("%s  %s（当前版本不可用）" % (icon, name))
        lab.setStyleSheet("color:#98a2b3;font-size:12px;")
        lab.setToolTip("这个功能在当前版本不可用（没找到入口：%s）" % want)
        return lab

    def _go():
        try:
            dialog.close()
        except Exception as e:
            from core.diagnostics import swallowed
            swallowed(__name__, e)
        try:
            fn()
        except Exception as e:
            QMessageBox.warning(None, name, "打开失败: %s" % str(e)[:80])

    lab = make_action_links([("%s  %s" % (icon, name), _go)])
    lab.setToolTip(desc)
    return lab


def make_hint(text):
    h = QLabel(str(text))
    h.setWordWrap(True)
    h.setStyleSheet("color:#667085;font-size:11px;")
    return h


def make_tab(title):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setSpacing(8)
    return w, lay


def make_scroll_tab(title, build):
    outer, layouts = make_tab(title)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    build(lay)
    lay.addStretch(1)
    scroll.setWidget(inner)
    layouts.addWidget(scroll)
    return outer
