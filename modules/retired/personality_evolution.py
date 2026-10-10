# -*- coding: utf-8 -*-
"""v26-3.3: 人格进化系统 完整版"""
import re, os, json


class PersonalityEvolution:
    """从交互中学习用户偏好，5维雷达图"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.prefs_path = os.path.join(self.base, "data", "personality_prefs.json")
        self.prefs = self._load()

    def _load(self):
        if os.path.exists(self.prefs_path):
            try:
                return json.load(open(self.prefs_path, encoding="utf-8"))
            except Exception:
                pass
        return {
            "reply_length": {"short": 0, "long": 0, "normal": 10},
            "tone": {"formal": 0, "casual": 5, "humorous": 3, "serious": 0},
            "emoji": {"like": 0, "dislike": 0, "normal": 5},
            "proactive": {"like": 0, "dislike": 0, "normal": 5},
        }

    def _save(self):
        tmp = self.prefs_path + ".tmp"
        json.dump(self.prefs, open(tmp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        os.replace(tmp, self.prefs_path)

    def record_preference(self, user_text):
        """从用户话里学习偏好"""
        if re.search(r'(短点|简短|别啰嗦|太长)', user_text):
            self.prefs["reply_length"]["short"] += 1
        if re.search(r'(详细点|多说点|具体点)', user_text):
            self.prefs["reply_length"]["long"] += 1
        if re.search(r'(正经|严肃)', user_text):
            self.prefs["tone"]["serious"] += 1
        if re.search(r'(别开玩笑|别闹)', user_text):
            self.prefs["tone"]["humorous"] -= 1
        if re.search(r'[\U0001F300-\U0001FAFF]', user_text):
            self.prefs["emoji"]["like"] += 1
        self._save()

    def get_radar(self):
        """5维雷达图数据"""
        rl = self.prefs["reply_length"]
        tone = self.prefs["tone"]
        emo = self.prefs["emoji"]
        # 归一化到0-1
        warmth = 0.7
        humor = min(1.0, max(0.0, tone.get("humorous", 0) / 10 + 0.3))
        detail = min(1.0, max(0.0, rl.get("long", 0) / 5 + 0.3))
        proact = 0.4
        emoji = min(1.0, emo.get("like", 0) / 5)
        return {
            "温暖": round(warmth, 2),
            "幽默": round(humor, 2),
            "详细": round(detail, 2),
            "主动": round(proact, 2),
            "活泼": round(emoji, 2),
        }

    def apply_hint(self):
        """生成人格提示，加到LLM系统提示里"""
        radar = self.get_radar()
        hints = []
        if radar["幽默"] > 0.6:
            hints.append("【可以幽默】偶尔开个玩笑")
        elif radar["幽默"] < 0.3:
            hints.append("【正经点】别开玩笑")
        if radar["详细"] > 0.6:
            hints.append("【可以详细】多说点细节")
        elif radar["详细"] < 0.3:
            hints.append("【简短回答】别啰嗦")
        if radar["活泼"] > 0.6:
            hints.append("【带点emoji】自然使用表情")
        return "\n".join(hints)

    def run(self, *a):
        return {"雷达": self.get_radar(), "提示": self.apply_hint()}
