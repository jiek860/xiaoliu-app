# -*- coding: utf-8 -*-
"""ChatMixin：空输入、任务模式、流式 token 和回复落地。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QPlainTextEdit, QTextEdit, QWidget, QListWidget,
    QListWidgetItem,
)
from PyQt5.QtCore import Qt  # noqa: E402

_app = QApplication.instance() or QApplication([])

from gui.mixins.chat_mixin import ChatMixin  # noqa: E402


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, cb):
        self.callbacks.append(cb)


class _Worker:
    instances = []

    def __init__(self, trunk, text, force_chat=False):
        self.trunk = trunk
        self.text = text
        self.force_chat = force_chat
        self.token = _Signal()
        self.done = _Signal()
        self.started = False
        _Worker.instances.append(self)

    def start(self):
        self.started = True


class _Chat(QTextEdit):
    def __init__(self):
        super().__init__()
        self.user_messages = []
        self.thinking = 0
        self.rendered = []
        self.history = []
        self.cleared = False

    def clear(self):
        self.cleared = True
        super().clear()

    def load_history(self, messages):
        self.history = list(messages or [])

    def append_user(self, text):
        self.user_messages.append(text)

    def append_thinking(self):
        self.thinking += 1
        return "anchor"

    def remove_from_anchor(self, _anchor):
        pass

    def split_group(self, _text):
        return []

    def render_reply(self, text, fallback_name=""):
        self.rendered.append((text, fallback_name))

    def append(self, text):
        self.rendered.append((text, "raw"))

    def append_system(self, text):
        self.rendered.append((text, "system"))

    def append_plain(self, name, text):
        self.rendered.append((name, "plain:" + text))

    def at_bottom(self, tolerance=24):
        return True

    def scroll_to_bottom(self):
        self.scrolled = True


class _Store:
    def __init__(self):
        self.messages = {
            "u": {"id": 1, "text": "上一条"},
            "a": {"id": 2, "text": "上一条回复"},
        }
        self.deleted = []
        self.branched = 0

    def last_message(self, _username, _session, role="u"):
        return self.messages.get(role)

    def delete_message_by_id(self, msg_id):
        self.deleted.append(msg_id)

    def branch_session(self, _username, _session):
        self.branched += 1
        return "branch-1"


class _Account:
    username = "tester"

    def __init__(self):
        self.session = "default"
        self.chat_store = _Store()

    def current_username(self):
        return self.username

    def save_line(self, *a, **k):
        self.lines = getattr(self, "lines", []) + [a]
        return True

    def load_history(self, limit=50):
        return [{"role": "u", "text": "hi"}]

    def switch_session(self, sid):
        self.session = sid

    def list_sessions(self):
        return [{"session_id": "default", "count": 3},
                {"session_id": "work", "count": 2}]


class _Trunk:
    base = BASE
    config = {"auto_tts": False}

    def _should_auto_task(self, _text):
        return False

    def _log(self, *_a, **_k):
        return None


class _Dummy(QWidget, ChatMixin):
    def __init__(self):
        super().__init__()
        self.input = QPlainTextEdit(self)
        self.chat = _Chat()
        self.account = _Account()
        self.trunk = _Trunk()
        self.ai_name = "小6"
        self.last_user_msg = 0
        self._chat_anchor = None
        self.task_sent = []
        self.focus_called = False
        self.session_list = QListWidget()

        class Status:
            def showMessage(self, *_a, **_k):
                return None

        self.statusBar = lambda: Status()

    def _composer_is_task(self):
        return False

    def _send_task(self, text):
        self.task_sent.append(text)
        return None

    def _mark_guide_event(self, _event):
        return None

    def _handle_last_task_result(self):
        return None

    def _update_empty_state(self):
        return None

    def _maybe_offer_install(self, _text):
        return None


def test_empty_input_does_not_send(monkeypatch):
    d = _Dummy()
    d.input.setPlainText("   ")
    monkeypatch.setattr(d.input, "setFocus", lambda: setattr(d, "focus_called", True))
    d.send()
    assert d.focus_called is True
    assert d.chat.user_messages == []


def test_task_mode_routes_to_task_runtime():
    d = _Dummy()
    d.input.setPlainText("整理资料")
    d._composer_is_task = lambda: True
    d.send()
    assert d.task_sent == ["整理资料"]


def test_send_starts_worker_and_clears_input(monkeypatch):
    import gui.mixins.chat_mixin as cm
    monkeypatch.setattr(cm, "StreamWorker", _Worker)
    monkeypatch.setattr("core.agent_router.route_goal",
                        lambda *a, **k: {"kind": "chat", "confidence": 1.0})
    d = _Dummy()
    d.input.setPlainText("你好")
    d.send()
    assert d.chat.user_messages == ["你好"]
    assert d.input.toPlainText() == ""
    assert _Worker.instances[-1].started is True


def test_on_token_and_reply_render():
    d = _Dummy()
    d._on_token("流式")
    assert "流式" in d.chat.toPlainText()
    d._on_reply("完整回复")
    assert d.chat.rendered[-1] == ("完整回复", "小6")

def test_edit_and_regenerate_last_message():
    d = _Dummy()
    d.account.chat_store.messages = {
        "u": {"id": 1, "text": "旧问题"},
        "a": {"id": 2, "text": "旧回复"},
    }
    d.edit_last_user_message()
    assert d.input.toPlainText() == "旧问题"
    assert d.chat.cleared is True
    assert d.account.chat_store.deleted == [2, 1]

    d.account.chat_store.messages = {
        "u": {"id": 3, "text": "再生成"},
        "a": {"id": 4, "text": "回复"},
    }
    sent = []
    d.send = lambda: sent.append(True)
    d.regenerate_last_reply()
    assert d.input.toPlainText() == "再生成"
    assert sent == [True]


def test_branch_and_session_switch_and_refresh_list():
    d = _Dummy()
    d._refresh_session_list()
    assert d.session_list.count() == 2
    item = d.session_list.item(1)
    d._on_session_clicked(item)
    assert d.account.session == "work"
    assert d.chat.history

    d.branch_current_conversation()
    assert d.account.chat_store.branched == 1
    assert d.account.session == "branch-1"


def test_persona_opening_and_proactive_hint():
    class Personality:
        def proactive_lines(self):
            return "想你了"

        def dream(self):
            return "梦见星空"

    d = _Dummy()
    d.trunk.modules = {"personality": Personality()}
    d._persona_opening()
    assert any("想你了" in x[0] for x in d.chat.rendered if isinstance(x, tuple))
    d.last_user_msg = 0
    d._check_proactive()
    assert len(d.chat.rendered) >= 2


class _RunningWorker(_Worker):
    def isRunning(self):
        return True

    def stop(self):
        self.stopped = True


def test_send_is_blocked_while_replying(monkeypatch):
    import gui.mixins.chat_mixin as cm
    monkeypatch.setattr(cm, "StreamWorker", _Worker)
    d = _Dummy()
    d.worker = _RunningWorker(None, "")
    d.input.setPlainText("再来一句")
    d.send()
    assert d.chat.user_messages == []       # 不并行发送
    assert any(tag == "system" for _, tag in d.chat.rendered)


def test_stop_reply_keeps_partial_and_clears_worker():
    d = _Dummy()
    w = _RunningWorker(None, "")
    d.worker = w
    d._stream_buf = ["写到一半", "的内容"]
    d._chat_anchor = "anchor"
    assert d.stop_reply() is True
    assert w.stopped is True
    assert d.worker is None
    # 停止后按 Markdown 渲染已收到的部分，并写入会话历史。
    assert ("写到一半的内容", "小6") in d.chat.rendered
    assert any(a[0] == "a" and "写到一半的内容" in a[1]
               for a in d.account.lines)
    assert ("已停止生成（已保留当前内容）", "system") in d.chat.rendered


def test_stop_reply_no_worker_returns_false():
    d = _Dummy()
    d.worker = None
    assert d.stop_reply() is False


def test_on_token_follows_bottom_only_when_pinned():
    class Pinned(_Chat):
        def at_bottom(self, tolerance=24):
            return False

    d = _Dummy()
    d.chat = Pinned()
    d._on_token("abc")
    assert not getattr(d.chat, "scrolled", False)
    d.chat = _Chat()
    d._on_token("def")
    assert getattr(d.chat, "scrolled", False) is True


def test_chat_view_system_and_plain_escape_html():
    from gui.chat_view import ChatView
    v = ChatView()
    v.append_system("<b>不要变粗</b>")
    assert "&lt;b&gt;" in v.toHtml()
    v.append_plain("小6", "<img src=x>\n第二行")
    assert "&lt;img" in v.toHtml()


class _StreamingChat(_Chat):
    def __init__(self):
        super().__init__()
        self.streams = []

    def stream_render(self, anchor, text, fallback_name="小6"):
        self.streams.append((text, anchor))
        return "anchor-%d" % len(self.streams)


def test_on_token_renders_first_frame_then_throttles():
    d = _Dummy()
    d.chat = _StreamingChat()
    d._on_token("你")
    assert d.chat.streams == [("你", None)]
    d._on_token("好")               # 节流窗口内不重绘
    assert len(d.chat.streams) == 1
    d._stream_rendered_at -= 1
    d._on_token("！")
    assert d.chat.streams[-1][0] == "你好！"


def test_chat_view_stream_render_replaces_previous_frame():
    from gui.chat_view import ChatView
    v = ChatView()
    anchor = v.stream_render(None, "第一帧")
    assert "第一帧" in v.toPlainText()
    anchor = v.stream_render(anchor, "第二帧")
    text = v.toPlainText()
    assert "第二帧" in text and "第一帧" not in text
    v.stream_render(anchor, "说明\n```python\nprint(1)")
    assert "print(1)" in v.toPlainText()


def test_tokens_arriving_after_stop_are_dropped():
    """Esc 之后已排队的 token 信号不能把半条内容追加到"已停止"后面。"""
    d = _Dummy()
    d.chat = _StreamingChat()
    d.worker = _RunningWorker(None, "")
    d._stream_buf = ["半句"]
    d.stop_reply()
    frames = list(d.chat.streams)
    d._on_token("迟到的一帧")
    assert d.chat.streams == frames
    assert d._stop_requested is True


def test_new_send_resets_previous_stop_flag(monkeypatch):
    import gui.mixins.chat_mixin as cm
    monkeypatch.setattr(cm, "StreamWorker", _Worker)
    monkeypatch.setattr("core.agent_router.route_goal",
                        lambda *a, **k: {"kind": "chat", "confidence": 1.0})
    d = _Dummy()
    d._stop_requested = True
    d.input.setPlainText("新问题")
    d.send()
    assert d._stop_requested is False
    # 新一条的 token 能正常显示（不会被上一条的停止标记吞掉）
    d._on_token("新回复")
    assert "新回复" in d.chat.toPlainText()


def test_markdown_closes_unclosed_code_fence():
    from gui.markdown_renderer import MarkdownRenderer
    md = MarkdownRenderer()
    html = md.render("说明\n```python\nprint(1)")
    assert "<pre" in html and "</pre>" in html
    assert md.codes == ["print(1)"]
