# -*- coding: utf-8 -*-
"""简单/高级模式与统一导航；实现已拆分到多个 mixin。"""
from __future__ import annotations

from gui.mixins.navigation_mixin import NavigationMixin
from gui.mixins.guidance_mixin import GuidanceMixin
from gui.mixins.task_entry_mixin import TaskEntryMixin
from gui.mixins.agent_launcher_mixin import AgentLauncherMixin
from gui.mixins.ui_actions_mixin import UIActionsMixin


class UIModeMixin(
    NavigationMixin,
    GuidanceMixin,
    TaskEntryMixin,
    AgentLauncherMixin,
    UIActionsMixin,
):
    pass
