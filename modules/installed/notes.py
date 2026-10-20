# -*- coding: utf-8 -*-
"""v26-7.1: 笔记工具"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time
from modules.base import BaseModule


class Notes(BaseModule):
    NAME = "笔记工具"
    VERSION = "1.0"

    TOOLS = [
        {"name": "note_add", "method": "add",
         "desc": "记一条笔记",
         "args": {"title": "标题", "content": "正文",
                  "tags": "标签，可空"},
         "hints": ["记笔记", "笔记", "记下来", "备忘"]},
        {"name": "note_search", "method": "search",
         "desc": "在笔记里搜关键词",
         "args": {"keyword": "要搜的词"},
         "readonly": True,
         "hints": ["搜笔记", "找笔记", "笔记里有没有"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "notes.json")
        self.notes = self._load()

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
        atomic_write_json(self.path, self.notes)

    def add(self, title, content, tags=None):
        self.notes.append({
            "title": title, "content": content,
            "tags": tags or [], "time": time.time(),
        })
        self._save()
        return {"ok": True}

    def search(self, keyword):
        return [n for n in self.notes
                if keyword in n["title"] or keyword in n["content"]]

    def run(self, *a):
        return {"笔记数": len(self.notes)}


