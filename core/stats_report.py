# -*- coding: utf-8 -*-
"""v26-6.2: 数据统计报表"""
import os, json


class StatsReport:
    """生成使用统计报告"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def generate(self, period="全部"):
        d = {
            "聊天消息": self._count_chats(),
            "记忆卡": self._count_cards(),
            "事件": self._count_calendar(),
        }
        return d

    def _count_chats(self):
        try:
            import sqlite3
            db = os.path.join(self.base, "data", "chats.db")
            if not os.path.exists(db):
                return 0
            c = sqlite3.connect(db)
            n = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            c.close()
            return n
        except Exception:
            return 0

    def _count_cards(self):
        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        if not os.path.exists(p):
            return 0
        return len(open(p, encoding="utf-8").readlines())

    def _count_calendar(self):
        p = os.path.join(self.base, "data", "calendar.json")
        if not os.path.exists(p):
            return 0
        try:
            return len(json.load(open(p, encoding="utf-8")))
        except Exception:
            return 0

    def run(self, *a):
        return self.generate()
