# -*- coding: utf-8 -*-
"""聊天记录编辑/分支基础测试。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.chat_store import ChatStore  # noqa: E402


def test_last_message_and_delete(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    cs.append("u", "u", "你好", session_id="s1")
    cs.append("u", "a", "你好呀", session_id="s1")
    assert cs.last_message("u", "s1", role="u")["text"] == "你好"
    assert cs.last_message("u", "s1", role="a")["text"] == "你好呀"
    assert cs.delete_last_message("u", "s1", role="a") is True
    assert cs.last_message("u", "s1", role="a") is None
    assert len(cs.load("u", "s1")) == 1


def test_branch_session_copies_history(tmp_path):
    cs = ChatStore(str(tmp_path / "chats.db"))
    cs.append("u", "u", "第一问", session_id="s1")
    cs.append("u", "a", "第一答", session_id="s1")
    sid = cs.branch_session("u", "s1")
    assert sid != "s1"
    msgs = cs.load("u", sid)
    assert [m["text"] for m in msgs] == ["第一问", "第一答"]
    # 原会话不受影响
    assert len(cs.load("u", "s1")) == 2
