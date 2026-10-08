# -*- coding: utf-8 -*-
"""P2-14: 消息分支 - 从某条消息分叉新会话"""
import os, json, time
import uuid


class MessageBranch:
    """消息分支管理"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def branch_from_message(self, session_id, message_index, new_title=None):
        """从某条消息分叉新会话"""
        chat_store = self.trunk.modules.get("chat_store")
        if not chat_store:
            return {"ok": False, "error": "chat_store未加载"}

        username = getattr(self.trunk, "current_user", "guest")
        # 读取原会话前N条消息
        msgs = chat_store.load(username, session_id, limit=message_index)

        # 创建新会话
        new_sid = "b_" + uuid.uuid4().hex[:10]
        # 把前N条消息复制到新会话
        for m in msgs:
            chat_store.append(username, m["role"], m["text"], new_sid)

        return {
            "ok": True,
            "原会话": session_id,
            "新会话": new_sid,
            "复制消息数": len(msgs),
        }

    def run(self, *a):
        return {"功能": "消息分支分叉"}
