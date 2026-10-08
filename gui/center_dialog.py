# -*- coding: utf-8 -*-
"""功能中心窗口 - 分组列表式"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QWidget, QFrame)
from PyQt5.QtCore import Qt
def show_center_dialog(parent, dlg, items):
    d, l = dlg("功能中心", w=680, h=620)
    head = QHBoxLayout()
    t = QLabel("功能中心")
    t.setStyleSheet("font-weight:bold;color:#1e40af;font-size:16px;")
    head.addWidget(t, stretch=1)
    close_btn = QPushButton("关闭")
    close_btn.setStyleSheet("padding:6px 14px;")
    close_btn.clicked.connect(d.close)
    head.addWidget(close_btn)
    l.addLayout(head)
    tip = QLabel("常用功能在主界面直接可用；以下是不常用的工具，按用途分组。")
    tip.setStyleSheet("color:#64748b;font-size:12px;padding:4px 0 12px 0;")
    l.addWidget(tip)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    host = QWidget()
    vbox = QVBoxLayout(host)
    vbox.setSpacing(18)
    vbox.setContentsMargins(8, 8, 8, 8)
    scroll.setWidget(host)
    l.addWidget(scroll, stretch=1)
    GROUP_RULES = [
        ("让它更聪明", ["知识库", "知识图谱", "插件", "学习"]),
        ("帮你干活", ["电脑控制", "机器人", "MCP"]),
        ("系统维护", ["系统", "日志", "备份", "自检"]),
    ]
    grouped = {g[0]: [] for g in GROUP_RULES}
    grouped["其他"] = []
    for icon, name, desc, cmd in items:
        placed = False
        for gname, kws in GROUP_RULES:
            if any(kw in name for kw in kws):
                grouped[gname].append((icon, name, desc, cmd))
                placed = True
                break
        if not placed:
            grouped["其他"].append((icon, name, desc, cmd))
    for gname, gitems in grouped.items():
        if not gitems:
            continue
        gt = QLabel(gname)
        gt.setStyleSheet(
            "font-weight:bold;font-size:14px;color:#334155;"
            "padding:6px 0;border-bottom:1px solid #e2e8f0;"
        )
        vbox.addWidget(gt)
        for icon, name, desc, cmd in gitems:
            row = QFrame()
            row.setObjectName("fcrow")
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet(
                "#fcrow { background:#ffffff; border:1px solid #e2e8f0; "
                "border-radius:8px; }"
                "#fcrow:hover { border:1px solid #4a9eff; background:#f8fbff; }"
            )
            hl = QHBoxLayout(row)
            hl.setContentsMargins(14, 10, 14, 10)
            hl.setSpacing(12)
            info = QVBoxLayout()
            info.setSpacing(2)
            nm = QLabel(name)
            nm.setStyleSheet("font-weight:bold;font-size:14px;color:#0f172a;")
            info.addWidget(nm)
            ds = QLabel(desc)
            ds.setStyleSheet("color:#64748b;font-size:12px;")
            ds.setWordWrap(True)
            info.addWidget(ds)
            hl.addLayout(info, 1)
            go = QLabel("打开 →")
            go.setStyleSheet("color:#4a9eff;font-size:12px;font-weight:bold;")
            hl.addWidget(go)
            def _make_handler(c=cmd, dd=d):
                def _go(_e):
                    dd.close()
                    try:
                        c()
                    except Exception:
                        pass
                return _go
            row.mousePressEvent = _make_handler()
            vbox.addWidget(row)
    vbox.addStretch(1)
    d.exec_()
