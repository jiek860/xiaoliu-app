# -*- coding: utf-8 -*-
"""聊天回复动作：复制、重发、编辑、继续话题与右键菜单接线。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import (QApplication, QPlainTextEdit, QTextEdit,  # noqa: E402
                             QWidget)

from gui import chat_reply_actions as ra  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Chat(QTextEdit):
    def __init__(self):
        super().__init__()
        self.systems = []

    def append_system(self, text):
        self.systems.append(text)


class _Win(QWidget):
    def __init__(self, messages=()):
        super().__init__()
        self.chat = _Chat()
        self.input = QPlainTextEdit()
        self._messages = list(messages)
        self.sent = 0
        self.worker = None

    def _recent_messages(self, limit=20):
        return self._messages[-limit:]

    def send(self):
        self.sent += 1


def test_last_texts_cache_then_history():
    w = _Win([{"role": "u", "text": "旧问题"},
              {"role": "a", "text": "旧回答"}])
    assert ra.last_user_text(w) == "旧问题"
    assert ra.last_reply_text(w) == "旧回答"
    w._last_user_text = "新问题"
    w._last_reply_text = "新回答"
    assert ra.last_user_text(w) == "新问题"
    assert ra.last_reply_text(w) == "新回答"


def test_copy_last_reply_sets_clipboard():
    w = _Win([{"role": "a", "text": "回答内容"}])
    assert ra.copy_last_reply(w) is True
    assert QApplication.clipboard().text() == "回答内容"
    empty = _Win()
    assert ra.copy_last_reply(empty) is False
    assert "还没有" in empty.chat.systems[-1]


def test_retry_last_sends_and_respects_running_worker():
    w = _Win([{"role": "u", "text": "重发我"}])
    assert ra.retry_last(w) is True
    assert w.sent == 1 and "重发我" in w.input.toPlainText()

    class _Running:
        def isRunning(self):
            return True

    w.worker = _Running()
    assert ra.retry_last(w) is False
    assert "还在回复" in w.chat.systems[-1]


def test_edit_last_fills_input_without_sending():
    w = _Win([{"role": "u", "text": "改一下"}])
    assert ra.edit_last(w) is True
    assert w.sent == 0 and "改一下" in w.input.toPlainText()


def test_continue_topic_prefills_input():
    w = _Win([{"role": "u", "text": "贪吃蛇游戏"}])
    assert ra.continue_topic(w) is True
    assert "贪吃蛇游戏" in w.input.toPlainText()


def test_missing_messages_report_and_return_false():
    w = _Win()
    assert ra.retry_last(w) is False
    assert ra.edit_last(w) is False
    assert ra.continue_topic(w) is False


def test_menu_has_expected_actions():
    w = _Win([{"role": "u", "text": "问题"}])
    menu = ra.show_menu(w)
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "复制上一条回复" in labels
    assert "重发上一条" in labels
    assert "继续这个话题" in labels
    assert "聊天话题时间线" in labels


def test_install_sets_custom_context_menu():
    w = _Win()
    hook = ra.install(w)
    assert hook is not None and w._chat_menu_hook is hook
    assert w.chat.contextMenuPolicy() == Qt.CustomContextMenu
