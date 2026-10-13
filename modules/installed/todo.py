# -*- coding: utf-8 -*-
"""v26-7.1: TODO待办工具"""
import os, json
from modules.base import BaseModule


class Todo(BaseModule):
    NAME = "待办工具"
    VERSION = "1.0"

    TOOLS = [
        {"name": "todo_add", "method": "add",
         "desc": "记一条待办事项",
         "args": {"text": "要做什么", "priority": "优先级 1-5，默认 3"},
         "hints": ["待办", "记一下要做", "提醒我", "todo", "任务清单"]},
        {"name": "todo_list", "method": "list_pending",
         "desc": "看看还有哪些待办没做",
         "args": {},
         "readonly": True,
         "hints": ["待办列表", "还有什么没做", "没做完的", "待办事项"]},
        {"name": "todo_done", "method": "done",
         "desc": "把某条待办标记为已完成",
         "args": {"idx": "第几条（从 1 开始，先查列表）"},
         "hints": ["做完了", "完成待办", "划掉"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "todo.json")
        self.items = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self):
        from core.safe import atomic_write_json
        atomic_write_json(self.path, self.items)

    def add(self, text, priority=3):
        self.items.append({"text": text, "priority": priority, "done": False})
        self._save()
        return {"ok": True}

    def list_pending(self):
        return [i for i in self.items if not i["done"]]

    def done(self, idx):
        if 0 <= idx < len(self.items):
            self.items[idx]["done"] = True
            self._save()
            return {"ok": True}
        return {"错误": "索引越界"}

    def run(self, *a):
        return {"总数": len(self.items), "待办": len(self.list_pending())}


