# -*- coding: utf-8 -*-
"""v26-6.1: 数据去重与清洗 完整版"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, sqlite3


class DataCleaner:
    """一键清洗所有数据：聊天/记忆/图谱"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."

    def clean_chats(self):
        """聊天记录去重：删除完全相同的连续消息"""
        db = os.path.join(self.base, "data", "chats.db")
        if not os.path.exists(db):
            return {"状态": "无数据库"}
        c = sqlite3.connect(db)
        try:
            rows = c.execute("""SELECT id, username, session_id, role, text FROM messages ORDER BY ts""").fetchall()
            deleted = 0
            last_key = None
            for row in rows:
                key = (row[1], row[2], row[3], row[4])
                if key == last_key:
                    c.execute("DELETE FROM messages WHERE id=?", (row[0],))
                    deleted += 1
                else:
                    last_key = key
            c.commit()
            return {"删除重复": deleted, "剩余": len(rows) - deleted}
        finally:
            c.close()

    def clean_cards(self):
        """记忆卡去重：相似度>0.8合并"""
        p = os.path.join(self.base, "data", "memory_cards.jsonl")
        if not os.path.exists(p):
            return {"状态": "无记忆卡"}
        cards = []
        for ln in open(p, encoding="utf-8"):
            try:
                cards.append(json.loads(ln))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        keep = []
        deleted = 0
        for c in cards:
            facts = "".join(c.get("facts", []))
            s1 = set(facts)
            dup = False
            for k in keep:
                s2 = set("".join(k.get("facts", [])))
                if s1 and s2:
                    sim = len(s1 & s2) / len(s1 | s2)
                    if sim > 0.8:
                        dup = True
                        deleted += 1
                        break
            if not dup:
                keep.append(c)
        with open(p, "w", encoding="utf-8") as f:
            for c in keep:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        return {"原始": len(cards), "保留": len(keep), "删除": deleted}

    def clean_graph(self):
        """知识图谱去重：删除完全相同的三元组"""
        p = os.path.join(self.base, "data", "graph.json")
        if not os.path.exists(p):
            return {"状态": "无图谱"}
        try:
            d = json.load(open(p, encoding="utf-8"))
            tris = d.get("三元组", []) if isinstance(d, dict) else d
            seen = set()
            keep = []
            for t in tris:
                key = (t.get("s"), t.get("p"), t.get("o"))
                if key not in seen:
                    seen.add(key)
                    keep.append(t)
            d = {"三元组": keep}
            tmp = p + ".tmp"
            json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, p)
            return {"原始": len(tris), "保留": len(keep), "删除": len(tris) - len(keep)}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def clean_all(self):
        return {
            "聊天记录": self.clean_chats(),
            "记忆卡": self.clean_cards(),
            "知识图谱": self.clean_graph(),
        }

    def run(self, *a):
        return self.clean_all()
