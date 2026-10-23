# -*- coding: utf-8 -*-
"""P2-3: GraphRAG 社区摘要

轻量实现（不用 networkx，内置 BFS 社区检测）

不负责的事项：
  - 不负责知识图谱构建（由 knowledge_graph 做）
  - 不负责向量检索（由 vector_store 做）
  - 不负责 LLM 调用（由 trunk.modules.llm 做）：
  1. 从知识图谱拿三元组
  2. 简单社区检测（连通分量）
  3. LLM 给每个社区写摘要
  4. 存 data/graph_communities.json
"""
import json, os, time


class GraphRAG:
    def __init__(self, trunk):
        self.trunk = trunk
        self.base = getattr(trunk, "base", ".")
        self.out_file = os.path.join(self.base, "data", "graph_communities.json")

    def _get_triples(self):
        """从 knowledge_graph 拿三元组"""
        kg = self.trunk.modules.get("knowledge_graph") if self.trunk else None
        if kg and hasattr(kg, "triples"):
            return kg.triples
        return []

    def _detect_communities(self, triples):
        """简单社区检测：连通分量"""
        # 建邻接表
        adj = {}
        for s, _p, o in triples:
            adj.setdefault(s, set()).add(o)
            adj.setdefault(o, set()).add(s)
        # BFS 找连通分量
        visited = set()
        communities = []
        for node in adj:
            if node in visited:
                continue
            comm = []
            queue = [node]
            while queue:
                n = queue.pop(0)
                if n in visited:
                    continue
                visited.add(n)
                comm.append(n)
                queue.extend(adj.get(n, set()) - visited)
            if len(comm) >= 2:  # 至少 2 个节点才算社区
                communities.append(comm)
        return communities

    def _summarize_community(self, nodes, triples):
        """LLM 写社区摘要"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return ""
        # 找和这个社区相关的三元组
        related = [(s, p, o) for s, p, o in triples if s in nodes or o in nodes]
        txt = "\n".join(f"{s} {p} {o}" for s, p, o in related[:20])
        try:
            return llm.chat(f"这些知识属于哪个主题？用一句话总结：\n{txt}")
        except Exception:
            return ""

    def build(self):
        """构建社区摘要"""
        triples = self._get_triples()
        if not triples:
            return {"ok": False, "error": "没有知识图谱数据"}
        communities = self._detect_communities(triples)
        result = []
        for i, comm in enumerate(communities):
            summary = self._summarize_community(comm, triples)
            result.append({
                "id": i,
                "nodes": comm,
                "summary": summary,
                "size": len(comm),
            })
        # 存盘
        data = {"communities": result, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        json.dump(data, open(self.out_file, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        return {"ok": True, "communities": len(result), "file": self.out_file}

    def query(self, question):
        """查询：先找相关社区摘要，再下钻三元组"""
        if not os.path.exists(self.out_file):
            return self.build()
        data = json.load(open(self.out_file, encoding="utf-8"))
        # 简单匹配：问题里的词出现在哪个社区摘要里
        relevant = []
        for comm in data.get("communities", []):
            if any(w in comm.get("summary", "") for w in question.split()):
                relevant.append(comm)
        return {"question": question, "relevant_communities": relevant[:5]}

    def run(self, *a):
        """标准入口：构建社区摘要"""
        return self.build()

    def start(self):
        """启动（占位）"""
        return {'ok': True}

    def stop(self):
        """停止（占位）"""
        return {'ok': True}

    def health(self):
        """健康检查"""
        return {'ok': True}
