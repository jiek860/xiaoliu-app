# -*- coding: utf-8 -*-
"""知识图谱 v10.0 - LLM真抽取+对话自动入图+多跳推理+RAG查询"""
import json, os, re
from datetime import datetime
from collections import deque

SYNONYMS = {
    "gpt": "大语言模型", "chatgpt": "大语言模型", "llm": "大语言模型",
    "python": "Python", "pyqt": "PyQt", "rag": "检索增强生成",
    "mcp": "模型上下文协议", "api": "接口",
}

def normalize(entity):
    if not entity: return ""
    s = str(entity).strip().strip('。，,. ：:')
    low = s.lower()
    if low in SYNONYMS: return SYNONYMS[low]
    return s

class KnowledgeGraph:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(self.base, "data", "graph.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data = {"三元组": []}
        # P1-2: 批量写盘标记，30秒最多写一次
        import time as _t
        self._dirty = False
        self._last_save = _t.time()
        self._save_interval = 30
        if os.path.exists(self.path):
            try:
                d = json.load(open(self.path, encoding="utf-8"))
                if isinstance(d, dict): self.data = d
                elif isinstance(d, list): self.data = {"三元组": d}
            except: pass

    def _save(self):
        """P1-2: 批量写盘，30秒一次，原子写"""
        import time as _t
        if not self._dirty:
            return
        import os as _os
        _tmp = self.path + ".tmp"
        json.dump(self.data, open(_tmp, "w", encoding="utf-8"), ensure_ascii=False)
        _os.replace(_tmp, self.path)
        self._dirty = False
        self._last_save = _t.time()

    def add(self, subj, pred, obj, confidence=1.0):
        subj, obj = normalize(subj), normalize(obj)
        if not subj or not obj: return
        self.data["三元组"].append({
            "s": subj, "p": pred, "o": obj,
            "time": datetime.now().strftime("%Y-%m-%d"),
            "confidence": confidence, "hits": 1,
        })
        if len(self.data["三元组"]) > 10000:
            self.data["三元组"] = self.data["三元组"][-5000:]
        self._dirty = True
        import time as _t
        if _t.time() - self._last_save > self._save_interval:
            self._save()

    def auto_extract(self, text):
        """v10: LLM真抽取三元组，不是正则"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            # 兜底正则
            extracted = []
            for m in re.finditer(r'(\w+?)(是|属于|有|包括|用)(\w+?)[。，]', text):
                extracted.append((m.group(1), m.group(2), m.group(3)))
                self.add(m.group(1), m.group(2), m.group(3))
            return extracted
        prompt = f"""从这段话提取实体关系三元组，每行一行：主体|关系|客体
不要编号，只输出三元组：
{text[:300]}"""
        try:
            r = llm.chat(prompt)
            extracted = []
            for line in r.split("\n"):
                parts = line.strip().split("|")
                if len(parts) == 3:
                    s, p, o = [x.strip() for x in parts]
                    if s and p and o and len(s)<15 and len(o)<15:
                        self.add(s, p, o)
                        extracted.append((s, p, o))
            return extracted
        except:
            return []

    def query(self, entity):
        entity = normalize(entity)
        results = [t for t in self.data["三元组"] if entity in t["s"] or entity in t["o"]]
        return {"实体": entity, "关系数": len(results), "关系": results[:20]}

    def multi_hop(self, start, end, max_depth=3):
        """v10: 多跳推理BFS"""
        start, end = normalize(start), normalize(end)
        adj = {}
        for t in self.data["三元组"]:
            adj.setdefault(t["s"], []).append(t["o"])
        queue = deque([(start, [start])])
        paths = []
        while queue and len(paths) < 20:
            node, path = queue.popleft()
            if node == end and len(path) > 1:
                paths.append("→".join(path)); continue
            if len(path) >= max_depth: continue
            for nxt in adj.get(node, []):
                if nxt not in path:
                    queue.append((nxt, path + [nxt]))
        return {"起点": start, "终点": end, "路径数": len(paths), "路径": paths[:10]}

    def expand(self, entity, depth=2, limit=30):
        """以实体为中心向外扩展 depth 跳，返回路径（供GUI可视化）"""
        entity = normalize(entity)
        adj = {}
        for t in self.data["三元组"]:
            adj.setdefault(t["s"], []).append((t["p"], t["o"]))
            adj.setdefault(t["o"], []).append(("<-" + str(t["p"]), t["s"]))
        frontier = [(entity, 0, [entity])]
        paths = []
        seen = {entity}
        while frontier:
            node, d, path = frontier.pop(0)
            if d > 0:
                paths.append({"路径": "→".join(path), "深度": d})
            if d >= depth or len(paths) >= limit:
                continue
            for p, o in adj.get(node, []):
                if o not in seen:
                    seen.add(o)
                    frontier.append((o, d + 1, path + [o]))
        return {"实体": entity, "深度": depth, "路径数": len(paths), "路径": paths}

    def rag_query(self, query, top_k=5):
        """BUG-18: RAG查询——词级匹配，中文2-gram"""
        def _tokenize(text):
            import re
            words = re.findall(r'[\w]+', text.lower())
            # 中文2-gram
            for m in re.finditer(r'[一-鿿]+', text):
                s = m.group()
                for i in range(len(s) - 1):
                    words.append(s[i:i+2])
            return set(words)
        q_words = _tokenize(query)
        scored = []
        for t in self.data["三元组"]:
            text = t.get("s","") + t.get("p","") + t.get("o","")
            overlap = len(q_words & _tokenize(text))
            if overlap > 0:
                scored.append((overlap, t))
        scored.sort(key=lambda x: -x[0])
        result = [f"{t['s']}{t['p']}{t['o']}" for _, t in scored[:top_k]]
        return {"查询": query, "相关知识": result}

    def add_dialog(self, user_text, assistant_text):
        """存对话：自动提取实体关系"""
        try:
            self.auto_extract(user_text)
            self.auto_extract(assistant_text)
        except:
            pass

    def status(self):
        return {"三元组数": len(self.data["三元组"])}

    def run(self, query=""):
        if query: return self.rag_query(query)
        return {"三元组数": len(self.data["三元组"])}

