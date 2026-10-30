# -*- coding: utf-8 -*-
"""历史分页 + 会话草稿混入。

历史分页
--------
以前一次性把最近 50 条全部渲染进聊天视图，想看更早的消息只能去
「历史记录」窗口。现在聊天视图自己按页加载：首屏 50 条，顶部提供
「加载更早」入口，点击后按 (ts, id) 游标再取一页并保持滚动位置。

会话草稿
--------
每个 (用户名, 会话) 保存一份未发送的输入。切换会话 / 新建会话 / 登录
切号时先落盘当前草稿，再恢复目标会话的草稿；发送成功后清空。输入变化
后节流落盘，程序重启也能恢复。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class HistoryDraftMixin:
    """聊天历史分页与会话草稿。"""

    _HISTORY_PAGE_SIZE = 50
    _DRAFT_SAVE_DELAY_MS = 400

    # ---------------- 历史分页 ----------------

    def _history_store(self):
        return getattr(getattr(self, "account", None), "chat_store", None)

    def _history_identity(self):
        acc = getattr(self, "account", None)
        return (getattr(acc, "username", "guest"),
                getattr(acc, "session", "default"))

    def _recent_messages(self, limit=20):
        """最近 N 条会话消息（指代消解 / 回复动作 / 话题时间线共用）。"""
        store = self._history_store()
        if store is None:
            return []
        try:
            username, sid = self._history_identity()
            return store.load_page(username, sid, limit=max(1, int(limit))) or []
        except Exception as e:  # 静默是故意的 - 读不到历史就当没有
            _x6_swallowed(__name__, e, "load recent messages")
            return []

    def _load_history_page(self):
        """渲染最近一页历史，返回是否还有更早的消息。"""
        store = self._history_store()
        username, sid = self._history_identity()
        page = int(getattr(self, "_HISTORY_PAGE_SIZE", 50) or 50)
        msgs = store.load_page(username, sid, limit=page + 1) or []
        has_older = len(msgs) > page
        if has_older:
            msgs = msgs[-page:]
        self._chat_has_older = has_older
        self._chat_cursor = ((msgs[0].get("ts"), msgs[0].get("id"))
                             if msgs else None)
        self.chat.clear()
        self.chat.load_history(msgs, has_older=has_older)
        return has_older

    def _reload_chat_history(self):
        """重建聊天视图：装载最近一页 + 恢复当前会话草稿。"""
        try:
            self._load_history_page()
        except Exception as e:
            _x6_swallowed(__name__, e, "load history page")
        try:
            self._restore_draft_for_current_session()
        except Exception as e:
            _x6_swallowed(__name__, e, "restore draft")
        try:
            self._update_empty_state()
        except Exception as e:
            _x6_swallowed(__name__, e, "update empty state")

    def _load_older_history(self):
        """按游标再取一页更早的消息，插入到聊天视图顶部。"""
        if not getattr(self, "_chat_has_older", False):
            return False
        cursor = getattr(self, "_chat_cursor", None)
        if not cursor:
            self._chat_has_older = False
            return False
        ts, mid = cursor
        store = self._history_store()
        username, sid = self._history_identity()
        page = int(getattr(self, "_HISTORY_PAGE_SIZE", 50) or 50)
        try:
            msgs = store.load_page(username, sid, before_ts=ts,
                                   before_id=mid, limit=page + 1) or []
        except Exception as e:
            _x6_swallowed(__name__, e, "load older history")
            return False
        has_older = len(msgs) > page
        if has_older:
            msgs = msgs[-page:]
        if not msgs:
            self._chat_has_older = False
            return False
        try:
            self.chat.prepend_history(msgs, has_older=has_older)
        except Exception as e:
            _x6_swallowed(__name__, e, "prepend history")
            return False
        self._chat_cursor = (msgs[0].get("ts"), msgs[0].get("id"))
        self._chat_has_older = has_older
        return True

    # ---------------- 会话草稿 ----------------

    def _setup_draft_autosave(self):
        """输入变化后节流落盘，避免每个按键都写一次 SQLite。"""
        try:
            from PyQt5.QtCore import QTimer
            self._draft_timer = QTimer(self)
            self._draft_timer.setSingleShot(True)
            self._draft_timer.setInterval(
                int(getattr(self, "_DRAFT_SAVE_DELAY_MS", 400) or 400))
            self._draft_timer.timeout.connect(self._save_draft_now)
            self.input.textChanged.connect(self._on_draft_changed)
        except Exception as e:
            _x6_swallowed(__name__, e, "setup draft autosave")

    def _on_draft_changed(self):
        timer = getattr(self, "_draft_timer", None)
        if timer is not None:
            try:
                timer.start()
            except Exception as e:
                _x6_swallowed(__name__, e, "restart draft timer")

    def _save_draft_now(self):
        """立即把当前输入落盘（空输入视为清空草稿）。"""
        timer = getattr(self, "_draft_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception as e:
                _x6_swallowed(__name__, e, "stop draft timer")
        store = self._history_store()
        inp = getattr(self, "input", None)
        if store is None or inp is None:
            return
        username, sid = self._history_identity()
        try:
            text = inp.toPlainText()
            if str(text or "").strip():
                store.set_draft(username, sid, text)
            else:
                store.clear_draft(username, sid)
        except Exception as e:
            _x6_swallowed(__name__, e, "save draft")

    def _clear_draft(self):
        store = self._history_store()
        if store is None:
            return
        username, sid = self._history_identity()
        try:
            store.clear_draft(username, sid)
        except Exception as e:
            _x6_swallowed(__name__, e, "clear draft")

    def _restore_draft_for_current_session(self):
        store = self._history_store()
        inp = getattr(self, "input", None)
        if store is None or inp is None:
            return
        timer = getattr(self, "_draft_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception as e:
                _x6_swallowed(__name__, e, "stop draft timer")
        username, sid = self._history_identity()
        try:
            text = store.get_draft(username, sid) or ""
        except Exception as e:
            _x6_swallowed(__name__, e, "read draft")
            return
        if inp.toPlainText() == text:
            return
        inp.setPlainText(text)
        try:
            self._update_empty_state()
        except Exception as e:
            _x6_swallowed(__name__, e, "update empty state")

    def _switch_chat_session(self, sid):
        """切换会话：先保存当前草稿，再切换、重建视图、恢复新草稿。"""
        self._save_draft_now()
        self.account.switch_session(sid)
        self._reload_chat_history()
        return sid
