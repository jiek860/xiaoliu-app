# -*- coding: utf-8 -*-
"""设置窗口公共小组件。"""
from __future__ import annotations

from PyQt5.QtWidgets import (QLabel, QPushButton, QWidget, QVBoxLayout,
                             QScrollArea, QMessageBox)


def make_open_button(dialog, commands, icon, name, desc, key=None):
    b = QPushButton("%s  %s" % (icon, name))
    b.setToolTip(desc)
    b.setMinimumHeight(34)
    want = key if key is not None else name
    fn = commands.get(want)
    if not callable(fn):
        b.setEnabled(False)
        b.setToolTip("这个功能在当前版本不可用（没找到入口：%s）" % want)
        return b

    def _go(_checked=False, f=fn, n=name):
        try:
            dialog.close()
        except Exception as e:
            from core.diagnostics import swallowed
            swallowed(__name__, e)
        try:
            f()
        except Exception as e:
            QMessageBox.warning(None, n, "打开失败: %s" % str(e)[:80])
    b.clicked.connect(_go)
    return b


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
