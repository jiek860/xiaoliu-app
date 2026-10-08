# -*- coding: utf-8 -*-
"""主动学习 v2.1 - 发现用户偏好 + 主动推荐 + 统计 + 清空 + 导出"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class ActiveLearning(BaseModule):
    NAME = "active_learning"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.prefs = {}
        self.interactions = []
        self.learn_count = 0

    @safe
    def observe(self, user_input, ai_response):
        """观察用户输入，学习偏好"""
        self.interactions.append({"用户": user_input[:50], "AI": ai_response[:50], "时间": time.strftime("%m-%d %H:%M")})
        if len(self.interactions) > 100:
            self.interactions = self.interactions[-100:]

        # 统计高频词
        words = user_input.split()
        for w in words:
            self.prefs[w] = self.prefs.get(w, 0) + 1

        self.learn_count += 1
        return {"ok": True}

    @safe
    def top_preferences(self, count=10):
        """获取用户高频偏好"""
        sorted_prefs = sorted(self.prefs.items(), key=lambda x: x[1], reverse=True)
        return sorted_prefs[:count]

    @safe
    def suggest(self):
        """主动推荐"""
        top = self.top_preferences(5)
        if not top:
            return {"建议": "多聊几次我就了解你了"}
        return {"建议": "你常聊：" + ", ".join([w for w, _ in top[:3]])}

    @safe
    def get_history(self, count=10):
        """获取交互历史"""
        return {"历史": self.interactions[-count:]}

    @safe
    def stats(self):
        """统计"""
        return {
            "交互数": len(self.interactions),
            "偏好词数": len(self.prefs),
            "学习次数": self.learn_count
        }

    @safe
    def clear(self):
        """清空学习记录"""
        self.prefs = {}
        self.interactions = []
        self.learn_count = 0
        return {"ok": True}

    @safe
    def export_profile(self):
        """导出用户画像"""
        top = self.top_preferences(10)
        profile = f"""用户画像
==========
学习次数: {self.learn_count}
偏好词数: {len(self.prefs)}
高频词: {", ".join([w for w, _ in top])}
"""
        return {"画像": profile}

    def run(self, *args):
        return self.stats()

    @safe
    def get_preference_detail(self, word):
        """获取某个偏好词的详情"""
        count = self.prefs.get(word, 0)
        return {"词": word, "出现次数": count}

    @safe
    def reset_preference(self, word):
        """重置某个偏好词"""
        if word in self.prefs:
            del self.prefs[word]
            return {"成功": True}
        return {"成功": False, "错误": "词不存在"}

    @safe
    def get_learning_rate(self):
        """学习进度"""
        if self.learn_count < 10:
            return {"进度": "刚认识", "等级": 1}
        elif self.learn_count < 50:
            return {"进度": "有点了解", "等级": 2}
        elif self.learn_count < 200:
            return {"进度": "很熟悉", "等级": 3}
        else:
            return {"进度": "老铁了", "等级": 4}
