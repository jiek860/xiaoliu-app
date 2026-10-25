# -*- coding: utf-8 -*-
"""批次4：聊天历史分页 + 会话草稿。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtCore import QUrl  # noqa: E402
from PyQt5.QtWidgets import QApplication, QPlainTextEdit, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.chat_store import ChatStore  # noqa: E402
from gui.chat_view import ChatView, OLDER_LINK_TEXT  # noqa: E402
from gui.mixins.history_draft_mixin import HistoryDraftMixin  # noqa: E402


def _seed(store, n=120, username="u", session="s1"):
    for i in range(n):
        store.append(username, "u" if i % 2 == 0 else "a",
                     "消息%d" % i, session_id=session)


# ---------------- ChatStore 分页 ----------------

def test_load_page_latest_and_older(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    _seed(cs)

    page1 = cs.load_page("u", "s1", limit=50)
    assert [m["text"] for m in page1] == ["消息%d" % i for i in range(70, 120)]
    assert len(cs.load_page("u", "s1", limit=200)) == 120

    cursor = page1[0]
    page2 = cs.load_page("u", "s1", before_ts=cursor["ts"],
                         before_id=cursor["id"], limit=50)
    assert [m["text"] for m in page2] == ["消息%d" % i for i in range(20, 70)]

    cursor = page2[0]
    page3 = cs.load_page("u", "s1", before_ts=cursor["ts"],
                         before_id=cursor["id"], limit=50)
    assert [m["text"] for m in page3] == ["消息%d" % i for i in range(0, 20)]

    cursor = page3[0]
    assert cs.load_page("u", "s1", before_ts=cursor["ts"],
                        before_id=cursor["id"], limit=50) == []


def test_load_page_is_session_isolated(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    _seed(cs, n=3, session="s1")
    _seed(cs, n=2, session="s2")
    assert len(cs.load_page("u", "s1")) == 3
    assert len(cs.load_page("u", "s2")) == 2
    assert cs.load_page("u", "s3") == []


# ---------------- ChatStore 草稿 ----------------

def test_draft_roundtrip_and_isolation(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    assert cs.get_draft("u", "s1") == ""
    cs.set_draft("u", "s1", "草稿A")
    cs.set_draft("u", "s2", "草稿B")
    cs.set_draft("v", "s1", "别人的草稿")
    assert cs.get_draft("u", "s1") == "草稿A"
    assert cs.get_draft("u", "s2") == "草稿B"
    assert cs.get_draft("v", "s1") == "别人的草稿"
    # 空文本等价于清空
    cs.set_draft("u", "s1", "   ")
    assert cs.get_draft("u", "s1") == ""


def test_draft_survives_restart(tmp_path):
    path = str(tmp_path / "chats.db")
    ChatStore(path).set_draft("u", "s1", "没发出去的半句话")
    assert ChatStore(path).get_draft("u", "s1") == "没发出去的半句话"


def test_draft_removed_with_session(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    cs.set_draft("u", "s1", "草稿")
    cs.delete_session("u", "s1")
    assert cs.get_draft("u", "s1") == ""


# ---------------- ChatView 分页渲染 ----------------

def test_chat_view_load_and_prepend_order():
    view = ChatView()
    view.resize(500, 300)
    view.show()
    first_page = [{"role": "u", "text": "第一页用户", "ts": 10.0},
                  {"role": "a", "text": "第一页回复", "ts": 11.0}]
    view.load_history(first_page, has_older=True)
    text = view.toPlainText()
    assert OLDER_LINK_TEXT in text
    assert text.index("第一页用户") < text.index("第一页回复")

    view.prepend_history([{"role": "u", "text": "更早的用户", "ts": 9.0}],
                         has_older=True)
    text = view.toPlainText()
    assert text.index(OLDER_LINK_TEXT) < text.index("更早的用户")
    assert text.index("更早的用户") < text.index("第一页用户")
    assert text.count(OLDER_LINK_TEXT) == 1

    view.prepend_history([{"role": "a", "text": "最早回复", "ts": 8.0}],
                         has_older=False)
    text = view.toPlainText()
    assert OLDER_LINK_TEXT not in text
    assert text.index("最早回复") < text.index("更早的用户")


def test_chat_view_prepend_respects_block_cap():
    view = ChatView()
    view.document().setMaximumBlockCount(10)
    view.load_history([{"role": "x", "text": "原来%d" % i} for i in range(6)],
                      has_older=True)
    view.prepend_history([{"role": "x", "text": "更早%d" % i}
                          for i in range(6)], has_older=False)
    assert view.document().blockCount() <= 10
    # 从尾部裁，刚插进来的更早消息必须还在
    text = view.toPlainText()
    assert "更早0" in text
    assert "更早5" in text


def test_chat_view_older_link_emits_action():
    view = ChatView()
    view.load_history([{"role": "u", "text": "内容", "ts": 1.0}],
                      has_older=True)
    got = []
    view.actionRequested.connect(got.append)
    view._on_anchor(QUrl("history://older"))
    assert got == ["history://older"]


# ---------------- 混入：分页 + 草稿流程 ----------------

class _ChatLog:
    def __init__(self):
        self.loaded = []
        self.prepended = []

    def clear(self):
        self.loaded = []

    def load_history(self, msgs, has_older=False):
        self.loaded.append((list(msgs), has_older))

    def prepend_history(self, msgs, has_older=False):
        self.prepended.append((list(msgs), has_older))


class _Account:
    def __init__(self, store, username="u", session="s1"):
        self.chat_store = store
        self.username = username
        self.session = session

    def switch_session(self, sid):
        self.session = sid


class _PageWidget(QWidget, HistoryDraftMixin):
    def __init__(self, store):
        super().__init__()
        self.input = QPlainTextEdit(self)
        self.chat = _ChatLog()
        self.account = _Account(store)

    def _update_empty_state(self):
        return None


def test_mixin_loads_pages_and_cursor(tmp_path):
    store = ChatStore(str(tmp_path / "chats.db"))
    _seed(store)
    w = _PageWidget(store)
    w._reload_chat_history()

    assert w._chat_has_older is True
    msgs, has_older = w.chat.loaded[-1]
    assert has_older is True
    assert [m["text"] for m in msgs] == ["消息%d" % i for i in range(70, 120)]

    assert w._load_older_history() is True
    msgs, has_older = w.chat.prepended[-1]
    assert has_older is True
    assert [m["text"] for m in msgs] == ["消息%d" % i for i in range(20, 70)]

    assert w._load_older_history() is True
    msgs, has_older = w.chat.prepended[-1]
    assert has_older is False
    assert [m["text"] for m in msgs] == ["消息%d" % i for i in range(0, 20)]

    assert w._load_older_history() is False


def test_mixin_short_history_has_no_older(tmp_path):
    store = ChatStore(str(tmp_path / "chats.db"))
    _seed(store, n=3)
    w = _PageWidget(store)
    w._reload_chat_history()
    assert w._chat_has_older is False
    assert w.chat.loaded[-1][1] is False
    assert w._load_older_history() is False


def test_mixin_draft_saved_and_restored_on_switch(tmp_path):
    store = ChatStore(str(tmp_path / "chats.db"))
    w = _PageWidget(store)

    w.input.setPlainText("会话一的草稿")
    w._save_draft_now()
    assert store.get_draft("u", "s1") == "会话一的草稿"

    w._switch_chat_session("s2")
    assert w.input.toPlainText() == ""

    w.input.setPlainText("会话二的草稿")
    w._save_draft_now()
    assert store.get_draft("u", "s2") == "会话二的草稿"

    w._switch_chat_session("s1")
    assert w.input.toPlainText() == "会话一的草稿"


def test_mixin_restores_draft_after_restart(tmp_path):
    path = str(tmp_path / "chats.db")
    first = _PageWidget(ChatStore(path))
    first.input.setPlainText("重启前的草稿")
    first._save_draft_now()

    second = _PageWidget(ChatStore(path))
    second._reload_chat_history()
    assert second.input.toPlainText() == "重启前的草稿"
