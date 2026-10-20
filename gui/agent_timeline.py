# -*- coding: utf-8 -*-
"""Agent 实时步骤时间线：所有 Agent 弹窗共用。"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextEdit, QSplitter, QFrame,
)


class AgentTimeline(QWidget):
    """计划 / 执行 / 验证 / 失败原因 / 下一步 的统一展示组件。"""

    STATUS_COLORS = {
        "pending": "#667085",
        "running": "#1976d2",
        "waiting": "#b45309",
        "done": "#15803d",
        "failed": "#b91c1c",
        "cancelled": "#6b7280",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = {}
        self._seq = 0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.status = QLabel("等待开始")
        self.status.setStyleSheet(
            "font-weight:700;color:#344054;padding:4px 2px;")
        head.addWidget(self.status, 1)
        self.progress = QLabel("")
        self.progress.setStyleSheet("color:#667085;font-size:12px;")
        head.addWidget(self.progress)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        left = QFrame()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("步骤 / 验证 / 下一步"))
        self.steps = QListWidget()
        self.steps.setMinimumWidth(280)
        self.steps.setStyleSheet(
            "QListWidget{font-family:'Microsoft YaHei';font-size:12px;}"
            "QListWidget::item{padding:5px 4px;border-bottom:1px solid #eef2f6;}")
        ll.addWidget(self.steps, 1)
        split.addWidget(left)

        right = QFrame()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("详情 / 失败原因 / 工具结果"))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        rl.addWidget(self.detail, 1)
        self.shot = QLabel("截图会显示在这里")
        self.shot.setAlignment(Qt.AlignCenter)
        self.shot.setMinimumHeight(150)
        self.shot.setStyleSheet(
            "background:#f8fafc;border:1px solid #e4e7ec;color:#98a2b3;"
            "border-radius:6px;")
        rl.addWidget(self.shot, 1)
        split.addWidget(right)
        split.setSizes([340, 620])
        root.addWidget(split, 1)
        self.detail.setPlainText(
            "每一步会显示：为什么做、看到了什么、执行结果、验证结果、下一步。")

    def clear(self):
        self._steps.clear()
        self._seq = 0
        self.steps.clear()
        self.detail.clear()
        self.shot.setText("截图会显示在这里")
        self.shot.setPixmap(QPixmap())
        self.status.setText("等待开始")
        self.progress.setText("")

    def set_status(self, text, state="running"):
        self.status.setText(str(text or ""))
        color = self.STATUS_COLORS.get(state, "#344054")
        self.status.setStyleSheet(
            "font-weight:700;color:%s;padding:4px 2px;" % color)

    def set_progress(self, value):
        try:
            v = max(0.0, min(1.0, float(value)))
            self.progress.setText("%d%%" % int(v * 100))
        except (TypeError, ValueError):
            self.progress.setText(str(value or ""))

    def add_step(self, title, detail="", status="running", key=""):
        self._seq += 1
        key = key or ("step_%d" % self._seq)
        item = QListWidgetItem("%s  %s" % (
            "" if status == "running" else "", title))
        item.setData(Qt.UserRole, key)
        item.setToolTip(str(detail or "")[:1000])
        self.steps.addItem(item)
        self.steps.scrollToBottom()
        self._steps[key] = {"item": item, "title": title,
                            "detail": detail, "status": status}
        self._paint(item, title, status)
        if detail:
            self.append_detail(title, detail)
        return key

    def update_step(self, key, title=None, detail="", status=None):
        rec = self._steps.get(key)
        if not rec:
            return self.add_step(title or detail or key, detail,
                                 status or "running", key=key)
        rec["title"] = title or rec["title"]
        rec["detail"] = detail or rec.get("detail", "")
        rec["status"] = status or rec.get("status", "running")
        self._paint(rec["item"], rec["title"], rec["status"])
        if detail:
            self.append_detail(rec["title"], detail)
        return key

    def _paint(self, item, title, status):
        mark = {
            "done": "", "failed": "", "waiting": "",
            "cancelled": "", "running": "", "pending": "",
        }.get(status, "")
        item.setText("%s  %s" % (mark, title))
        color = self.STATUS_COLORS.get(status, "#344054")
        item.setForeground(Qt.GlobalColor.black)
        try:
            from PyQt5.QtGui import QColor, QBrush
            item.setForeground(QBrush(QColor(color)))
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass

    def append_detail(self, title, detail):
        if not str(detail or "").strip():
            return
        current = self.detail.toPlainText()
        if current.startswith("每一步会显示"):
            current = ""
        self.detail.setPlainText(
            (current + ("\n\n" if current else "") +
             "【%s】\n%s" % (title, str(detail)[:5000])).strip())
        cur = self.detail.textCursor()
        cur.movePosition(cur.End)
        self.detail.setTextCursor(cur)

    def show_screenshot(self, path):
        path = str(path or "")
        if not path or not os.path.isfile(path):
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        self.shot.setPixmap(pix.scaled(
            self.shot.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.shot.setToolTip(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        pix = self.shot.pixmap()
        if pix is not None and not pix.isNull():
            self.shot.setPixmap(pix.scaled(
                self.shot.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
