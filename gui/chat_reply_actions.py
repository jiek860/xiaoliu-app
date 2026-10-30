# -*- coding: utf-8 -*-
"""聊天回复动作：右键菜单里的「复制 / 重发 / 编辑 / 继续这个话题」。

为什么单独成文件
----------------
`chat_mixin` 只管发送与流式渲染；这些动作是围绕"上一条消息"的便利操作，
单独放一个文件既方便测试，也避免聊天混入继续变长。

所有动作都优先用窗口上已有的 ``_last_reply_text`` / ``_last_user_text``，
没有再回落到会话历史，保证"刚启动/切会话"也能用。
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, Qt
from PyQt5.QtWidgets import QApplication, QMenu

from core.chat import referent, topic_index

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


def _recent(win, limit=20):
    getter = getattr(win, "_recent_messages", None)
    if callable(getter):
        try:
            return list(getter(limit) or [])
        except Exception as e:
            _x6_swallowed(__name__, e, "reply actions recent messages")
    return []


def _role(msg):
    if isinstance(msg, str):
        return "u"
    msg = msg or {}
    return str(msg.get("role") or msg.get("r") or msg.get("type") or "")


def _text(msg):
    if isinstance(msg, str):
        return msg
    msg = msg or {}
    return str(msg.get("text") or msg.get("content") or "")


def last_user_text(win):
    """上一条用户消息：优先窗口缓存，其次会话历史。"""
    text = str(getattr(win, "_last_user_text", "") or "").strip()
    if text:
        return text
    for msg in reversed(_recent(win)):
        if _role(msg) in ("", "u", "user", "human"):
            value = _text(msg).strip()
            if value:
                return value
    return ""


def last_reply_text(win):
    text = str(getattr(win, "_last_reply_text", "") or "").strip()
    if text:
        return text
    for msg in reversed(_recent(win)):
        if _role(msg) in ("a", "assistant", "ai", "bot"):
            value = _text(msg).strip()
            if value:
                return value
    return ""


def copy_last_reply(win):
    text = last_reply_text(win)
    QApplication.clipboard().setText(text)
    _say(win, "已复制上一条回复" if text else "还没有可复制的回复")
    return bool(text)


def retry_last(win):
    """重新发送上一条用户消息（正在回复时先提示停止）。"""
    worker = getattr(win, "worker", None)
    if worker is not None and worker.isRunning():
        _say(win, "上一条还在回复，按 Esc 停止后再重发")
        return False
    text = last_user_text(win)
    if not text:
        _say(win, "没有可重发的消息")
        return False
    win.input.setPlainText(text)
    win.send()
    return True


def edit_last(win):
    """把上一条用户消息放回输入框，方便改完再发（不自动发送）。"""
    text = last_user_text(win)
    if not text:
        _say(win, "没有可编辑的消息")
        return False
    win.input.setPlainText(text)
    win.input.setFocus()
    _say(win, "已放回输入框，改完再发送")
    return True


def continue_topic(win):
    """在输入框预填「继续这个话题」，让用户补一句或直接发送。"""
    topic = referent.last_topic(_recent(win)) or \
        topic_index.topic_of(_recent(win)[-1] if _recent(win) else "")
    if not topic:
        _say(win, "还没有可继续的话题")
        return False
    win.input.setPlainText("继续这个话题：%s\n（补充：）" % topic)
    win.input.setFocus()
    _say(win, "已预填话题「%s」" % topic)
    return True


def _say(win, text):
    chat = getattr(win, "chat", None)
    append = getattr(chat, "append_system", None)
    if callable(append):
        try:
            append(str(text))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "reply action notice")


def show_menu(win, pos=None):
    """聊天区右键菜单：复制 / 重发 / 编辑 / 继续话题 / 话题时间线。"""
    menu = QMenu(win.chat if hasattr(win, "chat") else win)
    menu.addAction("复制选中", lambda: win.chat.copy())
    menu.addAction("复制上一条回复", lambda: copy_last_reply(win))
    menu.addSeparator()
    menu.addAction("重发上一条", lambda: retry_last(win))
    menu.addAction("编辑上一条", lambda: edit_last(win))
    menu.addAction("继续这个话题", lambda: continue_topic(win))
    menu.addSeparator()
    menu.addAction("聊天话题时间线", lambda: _open_timeline(win))
    return menu


def _open_timeline(win):
    opener = getattr(win, "chat_topics_dialog", None)
    if callable(opener):
        return opener()
    from gui.chat_timeline import open_timeline
    return open_timeline(win)


class _MenuHook(QObject):
    """把右键事件转成菜单；以聊天视图为父，控件销毁时自动断开。"""

    def __init__(self, win):
        super().__init__(getattr(win, "chat", None))
        self.win = win

    def popup(self, pos):
        menu = show_menu(self.win, pos)
        try:
            menu.exec_(self.win.chat.mapToGlobal(pos))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "chat reply menu")


def install(win):
    """给聊天视图装右键菜单（替换默认菜单，保留复制选中）。"""
    chat = getattr(win, "chat", None)
    if chat is None:
        return None
    hook = _MenuHook(win)
    chat.setContextMenuPolicy(Qt.CustomContextMenu)
    chat.customContextMenuRequested.connect(hook.popup)
    win._chat_menu_hook = hook
    return hook
