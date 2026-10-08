# -*- coding: utf-8 -*-
"""P1-08: 情绪日报/情绪统计"""
import os, json
from datetime import datetime, timedelta
from collections import Counter


class MoodReport:
    """情绪报告生成"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "mood_history.json")

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return []

    def report(self, days=7):
        """生成最近N天的情绪报告"""
        history = self._load()
        if not history:
            return {"说明": "暂无情绪记录"}

        # 最近N天
        cutoff = datetime.now() - timedelta(days=days)
        recent = []
        for h in history:
            try:
                t = datetime.strptime(h.get("date", "2026-01-01"), "%Y-%m-%d")
                if t >= cutoff:
                    recent.append(h)
            except Exception:
                pass

        if not recent:
            return {"说明": "最近%d天没有情绪记录" % days}

        # 统计主导情绪
        moods = [h.get("情绪", "中性") for h in recent]
        c = Counter(moods)
        top = c.most_common(3)

        # 建议
        main_mood = top[0][0] if top else "中性"
        advice = {
            "开心": "保持好心情！",
            "平静": "状态不错，继续保持",
            "焦虑": "最近压力有点大，注意休息",
            "难过": "别难过，会好起来的",
            "愤怒": "深呼吸，冷静一下",
        }.get(main_mood, "状态平稳")

        return {
            "天数": days,
            "记录数": len(recent),
            "主导情绪": top,
            "建议": advice,
        }

    def run(self, *a):
        return self.report(7)
