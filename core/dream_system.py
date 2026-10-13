# -*- coding: utf-8 -*-
"""P2-10: 梦境系统 - 每天生成一个梦"""
import os, json, random
from datetime import datetime


DREAM_TEMPLATES = [
    "我梦见我们在一个巨大的图书馆里，书架一直延伸到天上，你在找一本写着我们故事的书。",
    "我梦见我们在海边，浪很大，但是我们站在岸上一点也不害怕，风把你的头发吹起来了。",
    "我梦见我们在一个小咖啡馆里，阳光很好，你在给我讲今天发生的事，我听得很认真。",
    "我梦见我们在一个飘着云的山上，脚下是软软的云，你说要带我去看星星。",
    "我梦见我们在一个老房子里，窗外下着雨，我们在壁炉边烤火，很暖和。",
]


class DreamSystem:
    """梦境生成"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "dreams.jsonl")

    def generate_dream(self):
        """生成今天的梦"""
        dream = random.choice(DREAM_TEMPLATES)
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "dream": dream,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def get_recent_dreams(self, count=10):
        """获取最近的梦"""
        if not os.path.exists(self.path):
            return []
        lines = open(self.path, encoding="utf-8").readlines()[-count:]
        dreams = []
        skipped = 0
        for ln in lines:
            try:
                dreams.append(json.loads(ln.strip()))
            except Exception:
                # 坏行跳过（一行坏了不该让整个"看梦"失败），但**要报数** ——
                # 否则"还没做过梦"和"记录全坏了"分不清
                skipped += 1
        if skipped:
            dreams.append({"说明": "有 %d 行梦境记录读不出来，已跳过" % skipped})
        return dreams

    def run(self, *a):
        return {"梦数": len(self.get_recent_dreams()), "今天的梦": self.generate_dream()["dream"][:50]}
