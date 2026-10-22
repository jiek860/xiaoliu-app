# -*- coding: utf-8 -*-
"""账号与聊天记录管理"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
from core.chat_store import ChatStore


class AccountManager:
    def __init__(self, trunk, base_dir: str):
        self.trunk = trunk
        self.base = base_dir
        self.chat_store = ChatStore(os.path.join(base_dir, "data", "chats.db"))
        self.username = "guest"
        self.session = "default"

    def try_restore_login(self):
        """启动时自动恢复上次登录态。

        只在"确实已激活且验签通过"时才成功；任何失败都返回原因，
        由调用方决定是弹登录框还是提示。
        """
        try:
            r = self.trunk.call("auth", "restore_session")
        except Exception as e:  # 静默是故意的 - 恢复失败就走正常登录
            _x6_swallowed(__name__, e)
            return {"ok": False, "原因": "auth 不可用: %s" % str(e)[:80]}
        # auth.restore_session() 返回 (ok, user, reason) 三元组
        if isinstance(r, (tuple, list)) and len(r) >= 2:
            ok, user = bool(r[0]), str(r[1] or "")
            why = str(r[2] if len(r) > 2 else "")
        elif isinstance(r, dict):
            ok = bool(r.get("ok"))
            user = str(r.get("user") or "")
            why = str(r.get("原因") or "")
        else:
            ok, user, why = False, "", "auth 返回了无法识别的结果"
        if ok and user:
            self.username = user
            return {"ok": True, "user": user}
        return {"ok": False, "原因": why or "恢复登录失败"}

    def current_username(self):
        try:
            r = self.trunk.call("auth", "whoami")
            if isinstance(r, dict):
                u = r.get("user")
                if u and u != "未登录":
                    return u
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return None

    # 注：原来的 chat_path_for(username) 已删除。
    # 它计算 data/chat_gui.jsonl 与 data/users/<名>/chat/gui.jsonl 这些 v5 的
    # JSONL 路径，但全项目没有任何调用方 —— 聊天记录现在全部走下面的
    # ChatStore(chats.db)。它还有 os.makedirs 的副作用，留着只会凭空建目录。

    def save_line(self, role: str, text: str):
        try:
            self.chat_store.append(self.username, role, str(text), session_id=self.session)
        except Exception as e:
            _x6_swallowed(__name__, e)
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
