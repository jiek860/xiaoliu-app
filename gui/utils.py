# -*- coding: utf-8 -*-
"""GUI工具函数 - 崩溃捕获、中文右键菜单、分组标题"""
import sys, os, traceback
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt


def install_crash_hook():
    """安装全局异常捕获——崩了写文件"""
    def _crash_hook(exc_type, exc_value, exc_tb):
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_dir = os.path.join(base, "data", "logs")
            os.makedirs(log_dir, exist_ok=True)
            from datetime import datetime
            with open(os.path.join(log_dir, "gui_crashes.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] GUI崩溃: {exc_type.__name__}: {exc_value}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _crash_hook


def zh_menu(widget):
    """中文右键菜单"""
    widget.setContextMenuPolicy(Qt.CustomContextMenu)
    def show_menu(pos):
        m = widget.createStandardContextMenu()
        for a in m.actions():
            txt = a.text()
            if "Copy" in txt: a.setText("复制")
            elif "Paste" in txt: a.setText("粘贴")
            elif "Cut" in txt: a.setText("剪切")
            elif "Undo" in txt: a.setText("撤销")
            elif "Redo" in txt: a.setText("重做")
            elif "Select All" in txt: a.setText("全选")
        m.exec_(widget.mapToGlobal(pos))
    widget.customContextMenuRequested.connect(show_menu)


def section_title(title):
    """功能页内的分类分组标题（浅蓝加粗 + 下划线分隔）"""
    lbl = QLabel(title)
    lbl.setStyleSheet("color:#1e40af;font-weight:bold;font-size:12px;"
                      "margin-top:12px;padding-bottom:4px;border-bottom:1px solid #e2e8f0;")
    return lbl
