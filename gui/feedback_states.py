# -*- coding: utf-8 -*-
"""统一反馈状态组件：Loading / Empty / ErrorCard / 动作链接。"""
from __future__ import annotations

from html import escape

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame,
)

from core.agent_harness import normalize_error

# 链接样式：蓝色 + 下划线，保证「看起来能点」，不靠 QPushButton 的边框
_LINK_CSS = "color:#1d4ed8;text-decoration:underline;font-size:12px;"


def make_action_links(actions, separator="　·　"):
    """把次要动作做成一排可点击链接，替代零散小按钮。

    为什么不是按钮：按钮预算只许降不许升，而「导出 / 刷新 / 关闭 / 暂停」
    这类动作在纯展示弹窗里都是一次性入口，用链接表达能力不变，
    又不会把控件位重新涨回去。链接同时支持键盘 Tab 到达。
    actions: [(文字, 无参回调), ...]
    """
    callbacks, parts = [], []
    for text, fn in actions:
        if not callable(fn):
            continue
        parts.append('<a href="%d" style="%s">%s</a>'
                     % (len(callbacks), _LINK_CSS, escape(str(text))))
        callbacks.append(fn)
    label = QLabel(separator.join(parts))
    label.setObjectName("actionLinks")
    label.setTextFormat(Qt.RichText)
    label.setTextInteractionFlags(
        Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
    label.setOpenExternalLinks(False)
    label.setFocusPolicy(Qt.TabFocus)
    if callbacks:
        label.setCursor(Qt.PointingHandCursor)

    def _run(href):
        try:
            idx = int(href or "")
        except (TypeError, ValueError):
            return
        if 0 <= idx < len(callbacks):
            callbacks[idx]()

    label.linkActivated.connect(_run)
    return label


def make_url_links(links, separator="　·　"):
    """一排外部链接（交给系统浏览器打开），同样不占按钮位。

    links: [(文字, URL), ...]
    """
    parts = ['<a href="%s" style="%s">%s</a>'
             % (escape(str(url), quote=True), _LINK_CSS, escape(str(text)))
             for text, url in links]
    label = QLabel(separator.join(parts))
    label.setObjectName("urlLinks")
    label.setTextFormat(Qt.RichText)
    label.setTextInteractionFlags(
        Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
    label.setOpenExternalLinks(True)
    label.setFocusPolicy(Qt.TabFocus)
    label.setCursor(Qt.PointingHandCursor)
    return label


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
        # 「技术细节」是展开/收起，不该占按钮位 → 富文本链接
        self.detail_btn = QLabel()
        self.detail_btn.setTextFormat(Qt.RichText)
        self.detail_btn.setOpenExternalLinks(False)
        self.detail_btn.linkActivated.connect(lambda _l: self._toggle_detail())
        self._set_detail_link("技术细节")
        self.detail = QLabel(self.env.get("technical_detail", ""))
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color:#7f1d1d;font-size:11px;")
        self.detail.hide()
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

    def _set_detail_link(self, text):
        self.detail_btn.setText(
            '<a href="toggle" style="color:#b42318;text-decoration:underline;'
            'font-size:11px;">%s</a>' % text)

    def _toggle_detail(self):
        visible = not self.detail.isVisible()
        self.detail.setVisible(visible)
        self._set_detail_link("收起技术细节" if visible else "技术细节")


def show_error_message(parent, error, action=None):
    card = ErrorCardWidget(error, action=action, parent=parent)
    card.show()
    return card
