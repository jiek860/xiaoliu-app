# -*- coding: utf-8 -*-
"""l45_personality v2.0 - 小6拟人化全套（强指令+示例+心境驱动+主动搭话+记忆带话）"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json, os, time, re, random
from datetime import datetime
from modules.base import BaseModule


from core.personality_state import PersonalityStateMixin
from core.personality_time_hints import PersonalityTimeHintsMixin
from core.personality_social_hints import PersonalitySocialHintsMixin
from core.personality_style_hints import PersonalityStyleHintsMixin


class PersonalityEngine(
    PersonalityStateMixin,
    PersonalityTimeHintsMixin,
    PersonalitySocialHintsMixin,
    PersonalityStyleHintsMixin,
    BaseModule,
):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "personality"

    VERSION = "1.0"

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.path = os.path.join(self.base, r"data\personality.json")
        self.data = self._load()

    def run(self, *a):
        return self.data

    def relation_title_hint(self):
        """根据 relation_stage 变称呼"""
        stage = self.data.get("relation_stage", 0)
        titles = {
            0: "【关系】刚认识，客气点，叫'你'就行",
            1: "【关系】聊过几次了，可以稍微熟一点",
            2: "【关系】算朋友了，会偶尔吐槽两句",
            3: "【关系】老铁了！可以开玩笑、互怼，不用端着",
            4: "【关系】过命交情！随便说，它懂你",
        }
        return titles.get(min(stage, 4), titles[0])
