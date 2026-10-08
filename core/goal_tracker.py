# -*- coding: utf-8 -*-
"""长期目标追踪 v1.0 - 自动建档+主动提醒"""
import os, json, re, time
from datetime import datetime


class GoalTracker:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(self.base, "data", "goals.json")
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return {"goals": []}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def detect_new_goal(self, user_text):
        """从用户话里检测新目标"""
        pats = [
            r"我要(学|做|完成|实现|搞)([^，。！？\n]{2,20})",
            r"我打算(学|做|完成)([^，。！？\n]{2,20})",
            r"计划(学|做|完成)([^，。！？\n]{2,20})",
        ]
        for p in pats:
            m = re.search(p, user_text)
            if m:
                title = m.group(1) + m.group(2)
                title = title.strip()
                # 避免重复
                if not any(g["title"] == title for g in self.data["goals"]):
                    self.add_goal(title)
                    return title
        return None

    def add_goal(self, title, deadline=None):
        gid = "g_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        goal = {
            "id": gid,
            "title": title,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "deadline": deadline,
            "progress": 0.0,
            "milestones": [],
            "notes": [],
            "last_check": datetime.now().strftime("%Y-%m-%d"),
        }
        self.data["goals"].append(goal)
        self._save()
        return gid

    def update_progress(self, gid, progress):
        for g in self.data["goals"]:
            if g["id"] == gid:
                g["progress"] = max(0.0, min(1.0, progress))
                g["last_check"] = datetime.now().strftime("%Y-%m-%d")
                self._save()
                return True
        return False

    def check_reminders(self):
        """3天没跟进的目标，返回提醒列表"""
        now = datetime.now()
        reminders = []
        for g in self.data["goals"]:
            if g.get("progress", 0) >= 1.0:
                continue
            try:
                last = datetime.strptime(g["last_check"], "%Y-%m-%d")
                if (now - last).days >= 3:
                    reminders.append(g)
            except Exception:
                pass
        return reminders

    def list_goals(self):
        return self.data["goals"]

    def delete_goal(self, gid):
        self.data["goals"] = [g for g in self.data["goals"] if g["id"] != gid]
        self._save()
        return True

    def run(self, *a):
        return {
            "目标数": len(self.data["goals"]),
            "进行中": len([g for g in self.data["goals"] if g.get("progress", 0) < 1.0]),
            "待提醒": len(self.check_reminders()),
        }
