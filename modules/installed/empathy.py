# -*- coding: utf-8 -*-
"""共情模块 v2.1 - 情绪识别 + 情绪回复 + 情绪记忆 + 情绪趋势 + 情绪总结 + 统计 + 导出"""
import re, sys, os, time
from core.safe import safe
from modules.base import BaseModule


class EmpathyModule(BaseModule):
    NAME = "empathy"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.emotion_history = []
        self.empathy_count = 0
        self.empathy_replies = {
            "开心": "真高兴听到你这么说！",
            "难过": "别难过，我陪你",
            "生气": "别生气，让你不爽了",
            "焦虑": "别担心，慢慢来",
        }

    @safe
    def feel(self, text=""):
        """识别情绪"""
        if not text:
            return {"情绪": "中性"}

        # 情绪关键词
        happy = ["开心", "高兴", "好", "谢谢", "棒", "哈哈", "笑", "愉快", "快乐"]
        sad = ["难过", "伤心", "失败", "失望", "哭", "郁闷", "沮丧", "低落"]
        angry = ["生气", "愤怒", "讨厌", "烦", "火", "气", "恼火", "暴怒"]
        anxious = ["担心", "害怕", "紧张", "焦虑", "慌", "不安", "忐忑"]

        for kw in happy:
            if kw in text:
                return {"情绪": "开心", "回复": self.empathy_replies["开心"]}
        for kw in sad:
            if kw in text:
                return {"情绪": "难过", "回复": self.empathy_replies["难过"]}
        for kw in angry:
            if kw in text:
                return {"情绪": "生气", "回复": self.empathy_replies["生气"]}
        for kw in anxious:
            if kw in text:
                return {"情绪": "焦虑", "回复": self.empathy_replies["焦虑"]}

        return {"情绪": "中性"}

    @safe
    def llm_empathy(self, user_input):
        """用LLM共情回复"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return None
        return llm.chat(f"用户说：{user_input[:100]}\n他情绪怎样？一句话回复:")

    @safe
    def record_emotion(self, emotion):
        """记录情绪历史"""
        self.emotion_history.append({"情绪": emotion, "时间": time.strftime("%m-%d %H:%M")})
        self.empathy_count += 1
        if len(self.emotion_history) > 50:
            self.emotion_history = self.emotion_history[-50:]
        return {"记录": emotion}

    @safe
    def get_mood(self):
        """获取当前情绪趋势"""
        if not self.emotion_history:
            return {"趋势": "正常"}
        from collections import Counter
        c = Counter([e["情绪"] for e in self.emotion_history[-10:]])
        return {"最近情绪": c.most_common(3)}

    @safe
    def mood_summary(self):
        """情绪总结"""
        if not self.emotion_history:
            return {"总结": "还没记录情绪"}
        from collections import Counter
        c = Counter([e["情绪"] for e in self.emotion_history])
        dominant = c.most_common(1)[0][0] if c else "中性"
        return {"主导情绪": dominant, "记录数": len(self.emotion_history)}

    @safe
    def get_history(self, count=10):
        """获取情绪历史"""
        return {"历史": self.emotion_history[-count:]}

    @safe
    def stats(self):
        """统计"""
        return {
            "总共情次数": self.empathy_count,
            "记录数": len(self.emotion_history)
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        m = self.mood_summary()
        report = f"""共情模块报告
==========
总共情次数: {s['总共情次数']}
记录数: {s['记录数']}
主导情绪: {m.get('主导情绪', '未知')}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.feel(args[0])
        return self.stats()
