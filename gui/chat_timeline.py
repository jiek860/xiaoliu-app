# -*- coding: utf-8 -*-
"""聊天话题时间线：列出本轮会话的话题，双击跳回原消息。

为什么单独成文件
----------------
`dialog_mixin` / `history_draft_mixin` 都已在行数上限附近；话题导航是
"读消息 -> 抽话题 -> 定位文本"的独立流程，放这里便于单独测试。

入口：命令面板「聊天话题时间线」（Ctrl+K 搜索）。不新增按钮。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QVBoxLayout)

from core.chat import topic_index

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


def timeline_items(messages, query="", max_topics=12):
    """消息 -> 话题列表（可按查询过滤）；纯函数，便于测试。"""
    items = topic_index.topics(messages, max_topics=max_topics)
    return topic_index.search(items, query)


def scroll_to_text(view, needle):
    """在聊天视图里定位第一处 ``needle``；找到返回 True。"""
    text = str(needle or "").strip()
    if not text or view is None:
        return False
    try:
        doc = view.document()
        cursor = doc.find(text)
        if cursor.isNull():
            return False
        view.setTextCursor(cursor)
        view.ensureCursorVisible()
        return True
    except Exception as e:  # 静默是故意的 - 定位失败只影响跳转
        _x6_swallowed(__name__, e, "chat timeline scroll")
        return False


def _messages(win, limit=300):
    getter = getattr(win, "_recent_messages", None)
    if callable(getter):
        try:
            return list(getter(limit) or [])
        except Exception as e:
            _x6_swallowed(__name__, e, "chat timeline messages")
    return []


class TimelineDialog(QDialog):
    """话题清单：顶部过滤框，双击一条跳回聊天里的原话。"""

    __test__ = False
    __tab_no_buttons__ = True

    def __init__(self, win, messages=None, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.messages = list(messages if messages is not None
                             else _messages(win))
        self.setWindowTitle("🕘 聊天话题时间线")
        self.resize(420, 460)
        self.setStyleSheet("QDialog{background:#ffffff;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        self.head = QLabel(topic_index.summary(
            topic_index.topics(self.messages)))
        self.head.setWordWrap(True)
        self.head.setStyleSheet("color:#57606a;font-size:11px;")
        lay.addWidget(self.head)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤话题…（双击跳回聊天）")
        self.filter.textChanged.connect(self.refresh)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{border:1px solid #d0d7de;border-radius:6px;"
            "font-size:12px;}"
            "QListWidget::item{padding:5px 8px;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.list.itemDoubleClicked.connect(self._jump)
        lay.addWidget(self.list, 1)
        self.refresh()

    def refresh(self, *_args):
        query = self.filter.text() if hasattr(self, "filter") else ""
        items = timeline_items(self.messages, query)
        self.list.clear()
        for item in items:
            row = QListWidgetItem("%s  ×%d" % (item.get("topic"),
                                               item.get("count", 1)))
            row.setData(Qt.UserRole, item.get("topic") or "")
            row.setToolTip("第 %d 条消息开始，双击跳转" %
                           (int(item.get("index") or 0) + 1))
            self.list.addItem(row)
        if not items:
            self.list.addItem(QListWidgetItem("（没有匹配的话题）"))
        return items

    def _jump(self, item):
        topic = item.data(Qt.UserRole) or ""
        if not topic:
            return
        if not scroll_to_text(getattr(self.win, "chat", None), topic):
            status = getattr(self.win, "_status_bar_message", None)
            if callable(status):
                status("话题「%s」不在当前视图（可能在更早的历史里）" % topic)


def open_timeline(win, parent=None):
    """打开话题时间线（命令面板入口）。"""
    return TimelineDialog(win, parent=parent)
