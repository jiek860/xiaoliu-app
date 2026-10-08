# -*- coding: utf-8 -*-
"""账号与聊天记录管理"""
import os
import json
from core.chat_store import ChatStore


class AccountManager:
    def __init__(self, trunk, base_dir: str):
        self.trunk = trunk
        self.base = base_dir
        self.chat_store = ChatStore(os.path.join(base_dir, "data", "chats.db"))
        self.username = "guest"
        self.session = "default"
        self.guest_chat = os.path.join(base_dir, "data", "chat_gui.jsonl")

    def current_username(self):
        try:
            r = self.trunk.call("auth", "whoami")
            if isinstance(r, dict):
                u = r.get("user")
                if u and u != "未登录":
                    return u
        except Exception:
            pass
        return None

    def chat_path_for(self, username):
        if not username:
            return self.guest_chat
        d = os.path.join(self.base, "data", "users", str(username), "chat")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return os.path.join(d, "gui.jsonl")

    def save_line(self, role: str, text: str):
        try:
            self.chat_store.append(self.username, role, str(text), session_id=self.session)
        except Exception:
            pass

    def load_history(self, limit: int = 50):
        return self.chat_store.load(self.username, session_id=self.session, limit=limit)

    def list_sessions(self):
        return self.chat_store.list_sessions(self.username)

    def new_session(self):
        self.session = self.chat_store.new_session(self.username)
        return self.session

    def switch_session(self, sid: str):
        self.session = sid

    def switch_user(self, username):
        self.username = username or "guest"
