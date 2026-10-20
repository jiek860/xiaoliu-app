# -*- coding: utf-8 -*-
"""v26-7.1: 日历工具"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json
from datetime import datetime
from modules.base import BaseModule


class Calendar(BaseModule):
    NAME = "日历工具"
    VERSION = "1.0"

    TOOLS = [
        {"name": "calendar_today", "method": "today",
         "desc": "看今天有什么日程安排",
         "args": {},
         "readonly": True,
         "hints": ["今天日程", "今天有什么安排", "日历", "今日安排"]},
        {"name": "calendar_add", "method": "add_event",
         "desc": "加一个日程事件",
         "args": {"title": "事件名", "date": "日期，如 2026-10-20",
                  "time_": "时间，可空，如 15:00"},
         "hints": ["加日程", "安排一下", "提醒我", "日历加"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "calendar.json")
        self.events = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return []

    def _save(self):
        from core.safe import atomic_write_json
        atomic_write_json(self.path, self.events)

    def add_event(self, title, date, time_=""):
        self.events.append({"title": title, "date": date, "time": time_, "done": False})
        self._save()
        return {"ok": True}

    def today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return [e for e in self.events if e["date"] == today]

    def run(self, *a):
        return {"事件数": len(self.events), "今天": len(self.today())}


