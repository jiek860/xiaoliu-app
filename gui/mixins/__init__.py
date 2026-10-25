# -*- coding: utf-8 -*-
"""JarvisWindow 的混入类集合"""
from gui.mixins.chat_mixin          import ChatMixin
from gui.mixins.dialog_mixin        import DialogMixin
from gui.mixins.voice_mixin         import VoiceMixin
from gui.mixins.system_mixin        import SystemMixin
from gui.mixins.lifecycle_mixin     import LifecycleMixin
from gui.mixins.ui_mode_mixin       import UIModeMixin
from gui.mixins.history_draft_mixin import HistoryDraftMixin

__all__ = [
    "ChatMixin",
    "DialogMixin",
    "VoiceMixin",
    "SystemMixin",
    "LifecycleMixin",
    "UIModeMixin",
    "HistoryDraftMixin",
]
