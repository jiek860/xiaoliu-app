# -*- coding: utf-8 -*-
"""发送草稿 / 输入历史混入（功能深化二期 · A1）。

从 ``gui/mixins/chat_mixin.py`` 拆出来：那边已到 600 行上限，这里只放
A1 的草稿与历史逻辑，方法名保持原样，ChatMixin 通过继承直接用，调用方无感。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class DraftMixin:
    """A1：发送草稿 / 输入历史"""

    def _draft_base(self):
        return getattr(self.trunk, "base", "") or ""

    def _draft_session_id(self):
        for name in ("session_id", "current_session", "chat_id", "_session_key"):
            val = getattr(self, name, None)
            if val:
                return str(val)
        return "default"

    def _ensure_draft_hooks(self):
        """幂等地挂上草稿自动保存（防抖 1.5s）并恢复上次未发送内容。"""
        if getattr(self, "_draft_hooks_ready", False):
            return
        try:
            from PyQt5.QtCore import QTimer
            from core import draft_store
            self._draft_timer = QTimer(self)
            self._draft_timer.setSingleShot(True)
            self._draft_timer.setInterval(1500)
            self._draft_timer.timeout.connect(self._save_current_draft)
            self.input.textChanged.connect(self._draft_timer.start)
            saved = draft_store.load_draft(self._draft_base(),
                                           self._draft_session_id())
            if saved and not self.input.toPlainText().strip():
                self.input.setPlainText(saved)
            self._draft_hooks_ready = True
        except Exception as e:  # 静默是故意的 - 草稿只是体验优化
            _x6_swallowed(__name__, e, "draft hooks")

    def _save_current_draft(self):
        try:
            from core import draft_store
            draft_store.save_draft(self._draft_base(), self._draft_session_id(),
                                   self.input.toPlainText())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "save draft")

    def _record_sent(self, text):
        """发送时记录：加输入历史 + 清掉该会话草稿。失败不影响发送。"""
        try:
            from core import draft_store
            draft_store.push_history(self._draft_base(), text)
            draft_store.clear_draft(self._draft_base(), self._draft_session_id())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "record sent")