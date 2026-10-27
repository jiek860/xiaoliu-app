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

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "笔记工具"
    VERSION = "1.0"

    TOOLS = [
        {
         "contract": {
             "params": {
                 "title": {"type": "string"},
                 "content": {"type": "string"},
                 "tags": {"type": "string"}
             },
             "returns": {"type": "object"},
             "description": "记一条笔记",
         },
         "name": "note_add", "method": "add",
         "desc": "记一条笔记",
         "args": {"title": "标题", "content": "正文",
                  "tags": "标签，可空"},
         "hints": ["记笔记", "笔记", "记下来", "备忘"]},
        {
         "contract": {
             "params": {
                 "keyword": {"type": "string"}
             },
             "returns": {"type": "object"},
             "description": "在笔记里搜关键词",
         },
         "name": "note_search", "method": "search",
         "desc": "在笔记里搜关键词",
         "args": {"keyword": "要搜的词"},
         "readonly": True,
         "hints": ["搜笔记", "找笔记", "笔记里有没有"]},
    ]
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or "."
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        _dir = os.path.join(self.base, "data", "plugin_data", "notes")
        os.makedirs(_dir, exist_ok=True)
        self.path = os.path.join(_dir, "notes.json")
        _legacy = os.path.join(self.base, "data", "notes.json")
        if not os.path.exists(self.path) and os.path.exists(_legacy):
            try: os.replace(_legacy, self.path)
            except OSError:  # 静默是故意的：旧数据迁移失败不阻断主流程
                pass
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


