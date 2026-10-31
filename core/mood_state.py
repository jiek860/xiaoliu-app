# -*- coding: utf-8 -*-
"""情绪状态机（功能深化二期 · E2 人格/情绪）。

从用户话语做轻量情绪判定（规则关键词，不调模型），并给出语气权重：

* frustrated / anxious 等负面情绪 -> 权重调高，回复更务实、少玩笑；
* excited -> 权重调低，可以更活泼。

``MoodState`` 记录情绪切换历史，可接进 ``core.personality_state`` /
``core.pipeline.prompt_assembler`` 的提示拼接处。
"""
from __future__ import annotations

MOODS = ("calm", "excited", "frustrated", "anxious")

_KEYWORDS = {
    "frustrated": ("好烦", "烦死", "烦人", "生气", "讨厌", "糟糕", "失败",
                   "不行", "崩溃", "烂透", "算了", "搞什么"),
    "anxious": ("焦虑", "担心", "紧张", "害怕", "来得及", "着急", "压力"),
    "excited": ("太棒", "开心", "爽", "喜欢", "太好了", "耶", "赞", "厉害"),
}

_WEIGHT = {"calm": 1.0, "excited": 0.8, "frustrated": 1.2, "anxious": 1.1}


def detect(text):
    """从一段文本判断情绪；无明显情绪信号返回 calm。"""
    text = str(text or "")
    best, best_score = "calm", 0
    for mood, kws in _KEYWORDS.items():
        score = sum(1 for k in kws if k in text)
        if score > best_score:
            best, best_score = mood, score
    return best


class MoodState:
    def __init__(self, mood="calm"):
        self.mood = mood if mood in MOODS else "calm"
        self.history = []

    def update(self, text, signals=None):
        """更新情绪：signals 显式给 mood 时优先，否则从文本判定。"""
        mood = (signals or {}).get("mood") or detect(text)
        if mood not in MOODS:
            mood = "calm"
        if mood != self.mood:
            self.history.append((self.mood, mood))
        self.mood = mood
        return self.mood

    def hint_weight(self):
        return _WEIGHT.get(self.mood, 1.0)

    def is_negative(self):
        return self.mood in ("frustrated", "anxious")

    def reset(self):
        self.mood = "calm"
        self.history = []