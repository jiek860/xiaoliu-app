# -*- coding: utf-8 -*-
"""P2-3: GraphRAG 社区摘要（官方随包模块）

职责：
  1. 从 knowledge_graph 读取三元组（兼容旧版 list 与新版 dict）
  2. 用连通分量做轻量社区检测（不依赖 networkx）
  3. 有 LLM 时给每个社区写一句话摘要，没有时用实体清单兜底
  4. 存 data/graph_communities.json（原子写）
  5. query() 先匹配社区摘要，再下钻三元组，返回实体与关系

不负责的事项：
  - 不负责知识图谱构建/实体抽取（由 knowledge_graph 做）
  - 不负责向量检索与重排（由 vector_store 做）
  - 不负责模型选择与密钥管理（由 llm 模块做）
"""
import json
import os
import re
import time

from modules.base import BaseModule

try:
    from core.plugin_errors import make_error
except ImportError:  # 独立加载时保持可用
    def make_error(code, message="", **_kwargs):
        return {"error": {"code": code, "message": message}}


class GraphRAG(BaseModule):
    """GraphRAG 社区摘要 + 社区/三元组两级检索。"""

    NAME = "graph_rag"
    VERSION = "1.1.0"
    NOT_RESPONSIBLE = ("知识图谱构建", "向量检索", "模型选择")

    TOOLS = [
        {
            "name": "graph_rag_build",
            "method": "build",
            "desc": "重建知识图谱社区摘要",
            "args": {},
            "readonly": False,
            "confirm": True,
            "hints": ["社区摘要", "图谱摘要", "GraphRAG", "重建图谱摘要"],
            "contract": {
                "params": {},
                "returns": {"type": "object"},
                "errors": ["PLUGIN_NOT_AVAILABLE", "PLUGIN_INTERNAL_ERROR",
                           "PLUGIN_CANCELLED"],
                "side_effects": ["filesystem_write:data/graph_communities.json"],
                "idempotent": True,
                "timeout_ms": 120000,
                "concurrency_safe": False,
                "description": "读取图谱三元组、检测社区并覆盖社区摘要文件",
                "not_responsible": ["知识图谱抽取", "向量检索"],
            },
        },
        {
            "name": "graph_rag_query",
            "method": "query",
            "desc": "按问题检索相关社区并下钻三元组",
            "args": {"question": "要查询的问题"},
            "readonly": True,
            "hints": ["图谱检索", "知识关系", "社区查询", "GraphRAG 查询"],
            "contract": {
                "params": {"question": {"type": "string", "required": True}},
                "returns": {"type": "object"},
                "errors": ["PLUGIN_MISSING_ARG", "PLUGIN_NOT_AVAILABLE",
                           "PLUGIN_BAD_OUTPUT"],
                "side_effects": ["filesystem_read:data/graph_communities.json"],
                "idempotent": True,
                "concurrency_safe": True,
                "description": "两级检索：先匹配社区摘要，再返回相关三元组和实体",
                "not_responsible": ["知识图谱构建", "向量检索"],
            },
        },
        {
            "name": "graph_rag_status",
            "method": "status",
            "desc": "查看社区摘要的构建状态",
            "args": {},
            "readonly": True,
            "hints": ["图谱摘要状态", "社区摘要有多少"],
            "contract": {
                "params": {},
                "returns": {"type": "object"},
                "errors": ["PLUGIN_INTERNAL_ERROR"],
                "side_effects": ["filesystem_read:data/graph_communities.json"],
                "idempotent": True,
                "concurrency_safe": True,
                "timeout_ms": 5000,
                "description": "返回已保存的社区数、三元组数与更新时间",
                "not_responsible": ["重建摘要"],
            },
        },
    ]

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.out_file = os.path.join(self.base, "data", "graph_communities.json")
        self._last_count = 0
        self._last_triples = 0
        self._last_updated = ""
        self._last_error = ""
        self._stop_event = None
        try:  # 并发停止用；导入失败时退化为普通构建
            import threading
            self._stop_event = threading.Event()
        except Exception:
            self._stop_event = None
        self._refresh_saved_stats()

    # ------------------------------------------------------------------ 数据
    def _refresh_saved_stats(self):
        """读取已保存文件的统计；失败只记录，不抛异常。"""
        try:
            data = self._load_saved()
            communities = data.get("communities") if isinstance(data, dict) else None
            if isinstance(communities, list):
                self._last_count = len(communities)
            self._last_triples = int(data.get("triples") or 0) if isinstance(data, dict) else 0
            self._last_updated = str(data.get("updated") or "") if isinstance(data, dict) else ""
        except Exception as e:
            self._last_error = "读取旧摘要失败: %s" % str(e)[:120]

    def _load_saved(self):
        if not os.path.exists(self.out_file):
            return {}
        with open(self.out_file, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _norm_triple(item):
        if isinstance(item, dict):
            s, p, o = item.get("s"), item.get("p"), item.get("o")
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            s, p, o = item[0], item[1], item[2]
        else:
            return None
        s = str(s or "").strip()
        p = str(p or "").strip()
        o = str(o or "").strip()
        if not s or not o:
            return None
        return (s, p, o)

    def _get_triples(self):
        """从 knowledge_graph 或 graph.json 拿三元组（修复读错属性名）。"""
        raw = []
        kg = self.trunk.modules.get("knowledge_graph") if self.trunk else None
        if not kg and self.trunk and hasattr(self.trunk, "call"):
            self.trunk.call("knowledge_graph", "__no__")
            kg = self.trunk.modules.get("knowledge_graph")
        if kg is not None:
            data = getattr(kg, "data", None)
            if isinstance(data, dict):
                raw = data.get("三元组") or []
            if not raw:
                raw = getattr(kg, "triples", None) or []
        if not raw:
            path = os.path.join(self.base, "data", "graph.json")
            try:
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    raw = data.get("三元组", []) if isinstance(data, dict) else data
            except Exception as e:
                self._last_error = "读取 graph.json 失败: %s" % str(e)[:120]
                raw = []
        out, seen = [], set()
        for item in raw if isinstance(raw, (list, tuple)) else []:
            triple = self._norm_triple(item)
            if triple and triple not in seen:
                seen.add(triple)
                out.append(triple)
            if len(out) >= 20000:
                break
        return out

    # ------------------------------------------------------------------ 社区
    def _detect_communities(self, triples):
        """简单社区检测：无向连通分量，至少 2 个节点。"""
        adj = {}
        for s, _p, o in triples:
            adj.setdefault(s, set()).add(o)
            adj.setdefault(o, set()).add(s)
        visited = set()
        communities = []
        for node in sorted(adj):
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
                queue.extend(sorted(adj.get(n, set()) - visited))
            if len(comm) >= 2:
                communities.append(comm)
        return communities

    @staticmethod
    def _tokenize(text):
        words = re.findall(r"[\w]+", str(text or "").lower())
        for m in re.finditer(r"[\u4e00-\u9fff]+", str(text or "")):
            s = m.group()
            for i in range(len(s) - 1):
                words.append(s[i:i + 2])
        return set(words)

    @staticmethod
    def _fallback_summary(nodes):
        names = "、".join(nodes[:6])
        if len(nodes) > 6:
            names += " 等"
        return "包含 %s（共 %d 个实体）" % (names, len(nodes))

    def _summarize_community(self, nodes, related):
        """LLM 写社区摘要；没有模型或调用失败时用实体清单兜底。"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if llm and hasattr(llm, "chat") and related:
            txt = "\n".join("%s %s %s" % t for t in related[:20])
            try:
                summary = llm.chat(
                    "下面这些知识属于哪个主题？用一句话总结（不超过 40 字）：\n"
                    + txt)
                summary = str(summary or "").strip()
                if summary:
                    return summary
            except Exception as e:
                self._last_error = "社区摘要生成失败: %s" % str(e)[:120]
        return self._fallback_summary(nodes)

    def build(self):
        """构建社区摘要。"""
        self._last_error = ""
        if self._stop_event is not None and self._stop_event.is_set():
            return self._failure("PLUGIN_CANCELLED", "模块已停止，未构建摘要")
        triples = self._get_triples()
        if not triples:
            return self._failure(
                "PLUGIN_NOT_AVAILABLE",
                "没有知识图谱数据；先聊几句让 knowledge_graph 抽取三元组，"
                "或检查 data/graph.json 是否存在")
        communities = self._detect_communities(triples)
        result = []
        for i, comm in enumerate(communities):
            if self._stop_event is not None and self._stop_event.is_set():
                return self._failure("PLUGIN_CANCELLED", "构建过程中被停止")
            node_set = set(comm)
            related = [(s, p, o) for s, p, o in triples
                       if s in node_set or o in node_set]
            result.append({
                "id": i,
                "nodes": comm,
                "summary": self._summarize_community(comm, related),
                "size": len(comm),
            })
        payload = {
            "communities": result,
            "triples": len(triples),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            os.makedirs(os.path.dirname(self.out_file), exist_ok=True)
            tmp = self.out_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.out_file)
        except Exception as e:
            self._last_error = "写社区摘要失败: %s" % str(e)[:120]
            return self._failure("PLUGIN_INTERNAL_ERROR",
                                 "社区摘要写入失败，请检查 data/ 目录权限")
        self._last_count = len(result)
        self._last_triples = len(triples)
        self._last_updated = payload["updated"]
        self._add_history("构建社区摘要: %d 个社区" % len(result))
        return {"ok": True, "communities": len(result),
                "triples": len(triples), "file": self.out_file,
                "updated": payload["updated"]}

    # ------------------------------------------------------------------ 查询
    def query(self, question):
        """两级检索：先找相关社区，再下钻三元组。"""
        q = str(question or "").strip()
        if not q:
            return self._failure("PLUGIN_MISSING_ARG",
                                 "缺少 question（要查询的问题）")
        if not os.path.exists(self.out_file):
            built = self.build()
            if not built.get("ok"):
                return built
        try:
            data = self._load_saved()
        except Exception as e:
            self._last_error = "读取社区摘要失败: %s" % str(e)[:120]
            return self._failure("PLUGIN_BAD_OUTPUT",
                                 "社区摘要文件损坏，请先重建摘要")
        communities = data.get("communities") or []
        if not isinstance(communities, list):
            return self._failure("PLUGIN_BAD_OUTPUT",
                                 "社区摘要格式不对，请先重建摘要")
        q_words = self._tokenize(q)
        scored = []
        for comm in communities:
            if not isinstance(comm, dict):
                continue
            nodes = [str(n) for n in (comm.get("nodes") or [])]
            text = str(comm.get("summary") or "") + " " + " ".join(nodes)
            score = len(q_words & self._tokenize(text))
            for node in nodes:
                if node and node in q:
                    score += 5
            if score:
                scored.append((score, comm))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("id"))))
        relevant = [dict(comm, score=score) for score, comm in scored[:5]]
        nodes = set()
        for comm in relevant:
            nodes.update(str(n) for n in (comm.get("nodes") or []))
        triples = self._get_triples()
        related = []
        for s, p, o in triples:
            if s not in nodes and o not in nodes:
                continue
            score = len(q_words & self._tokenize(s + " " + p + " " + o))
            related.append((score, s, p, o))
        related.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
        rows = [{"s": s, "p": p, "o": o} for _score, s, p, o in related[:20]]
        entities = sorted({row["s"] for row in rows} | {row["o"] for row in rows})
        return {
            "ok": True,
            "question": q,
            "relevant_communities": relevant,
            "triples": rows,
            "entities": entities,
            "hint": "" if relevant else "没有命中社区，可先重建摘要或换个关键词",
        }

    # ------------------------------------------------------------------ 状态
    def status(self):
        try:
            data = self._load_saved()
            communities = data.get("communities") or []
            count = len(communities) if isinstance(communities, list) else 0
            return {
                "ok": True,
                "三元组": int(data.get("triples") or 0),
                "社区": count,
                "文件": self.out_file,
                "更新时间": str(data.get("updated") or ""),
                "运行阶段": self.health().get("stage", ""),
            }
        except Exception as e:
            self._last_error = "读取状态失败: %s" % str(e)[:120]
            return self._failure("PLUGIN_INTERNAL_ERROR", "社区摘要状态读取失败")

    def health(self):
        info = super().health()
        info.update({
            "模块": self.NAME,
            "有摘要": os.path.exists(self.out_file),
            "社区": self._last_count,
            "三元组": self._last_triples,
            "上次构建": self._last_updated,
            "last_error": self._last_error[:200],
        })
        return info

    def run(self, *args):
        """标准入口：带问题 -> 查询；不带 -> 构建摘要。"""
        self._count += 1
        question = args[0] if args and isinstance(args[0], str) else ""
        if question.strip():
            return self.query(question)
        return self.build()

    # ------------------------------------------------------------------ 生命周期
    def _on_start(self):
        os.makedirs(os.path.dirname(self.out_file), exist_ok=True)
        if self._stop_event is not None:
            self._stop_event.clear()

    def _on_stop(self):
        if self._stop_event is not None:
            self._stop_event.set()

    # ------------------------------------------------------------------ 错误
    @staticmethod
    def _failure(code, message, **extra):
        out = {"ok": False}
        out.update(make_error(code, message, module="graph_rag"))
        out.update(extra)
        return out
