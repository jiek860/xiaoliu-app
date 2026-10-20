# -*- coding: utf-8 -*-
"""统一反馈状态组件：Loading / Empty / ErrorCard。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame,
)

from core.agent_harness import normalize_error


class LoadingWidget(QWidget):
    def __init__(self, text="正在处理", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.label)
        lay.addWidget(self.bar)

    def set_text(self, text):
        self.label.setText(str(text))


class EmptyStateWidget(QWidget):
    def __init__(self, title="暂无内容", message="", action_label="",
                 action=None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addStretch(1)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size:16px;font-weight:700;color:#344054;")
        lay.addWidget(t)
        if message:
            m = QLabel(message)
            m.setWordWrap(True)
            m.setAlignment(Qt.AlignCenter)
            m.setStyleSheet("color:#667085;font-size:12px;")
            lay.addWidget(m)
        if action_label and callable(action):
            row = QHBoxLayout()
            row.addStretch(1)
            b = QPushButton(action_label)
            b.clicked.connect(action)
            row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        lay.addStretch(1)


class ErrorCardWidget(QFrame):
    def __init__(self, error, action=None, parent=None):
        super().__init__(parent)
        self.env = normalize_error(error)
        self.setStyleSheet(
            "ErrorCardWidget{background:#fff5f5;border:1px solid #fecaca;"
            "border-radius:10px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        title = QLabel(self.env["title"])
        title.setStyleSheet("color:#b42318;font-weight:700;font-size:13px;")
        lay.addWidget(title)
        msg = QLabel(self.env["message"])
        msg.setWordWrap(True)
        msg.setStyleSheet("color:#7a271a;font-size:12px;")
        lay.addWidget(msg)
        row = QHBoxLayout()
        self.detail_btn = QPushButton("技术细节")
        self.detail_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#b42318;"
            "padding:2px;font-size:11px;text-align:left;}")
        self.detail = QLabel(self.env.get("technical_detail", ""))
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#7f1d1d;font-size:11px;")
        self.detail.hide()
        self.detail_btn.clicked.connect(self._toggle_detail)
        row.addWidget(self.detail_btn)
        if callable(action):
            b = QPushButton(self.env["next_action"]["label"])
            b.clicked.connect(action)
            b.setStyleSheet(
                "QPushButton{background:#b42318;color:white;border:none;"
                "border-radius:7px;padding:5px 10px;font-size:12px;}")
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.detail)

    def _toggle_detail(self):
        visible = not self.detail.isVisible()
        self.detail.setVisible(visible)
        self.detail_btn.setText("收起技术细节" if visible else "技术细节")


def show_error_message(parent, error, action=None):
    card = ErrorCardWidget(error, action=action, parent=parent)
    card.show()
    return card
