# -*- coding: utf-8 -*-
"""上下文构建：并行检索 + 联网搜索 + 工具调用"""
import concurrent.futures
import time


class ContextBuilder:
    def __init__(self, trunk):
        self.trunk = trunk

    _TRIGGERS = (
        "怎么", "如何", "为什么", "写", "帮我", "代码", "python", "PyQt",
        "报错", "修复", "安装", "配置", "教程", "解释", "分析", "对比",
        "区别", "什么是", "什么意思", "查", "搜", "最新", "今天", "新闻",
        "价格", "天气", "下雨", "气温", "几度", "预报", "下载", "官网",
        "github", "GitHub", "文件", "读", "运行", "启动", "崩溃", "错误",
        "异常", "优化", "性能", "设计", "方案", "计划", "写一个", "做一个",
    )

    def is_simple(self, user_input: str) -> bool:
        has_complex = any(w in user_input for w in self._TRIGGERS)
        return len(user_input.strip()) <= 15 and not has_complex

    def _ctx_vector(self, user_input: str) -> str:
        try:
            vs = self.trunk.modules.get("vector_store")
            if not vs:
                return ""
            tk = self.trunk.rule("检索.top_k",
                                 self.trunk.config.get("retrieval_top_k", 3))
            rs = vs.search(user_input, top_k=tk)
            return "\n".join(r.get("text", "")[:100] for r in rs) if rs else ""
        except Exception:
            return ""

    def _ctx_memory(self, user_input: str) -> str:
        try:
            ml = self.trunk.modules.get("memory_loop")
            if not ml:
                self.trunk._load_lazy("memory_loop")
                ml = self.trunk.modules.get("memory_loop")
            if not ml or not hasattr(ml, "recall"):
                return ""
            out = ""
            for item in ml.recall(user_input, top_k=2, hours=48):
                if item.get("type", "") == "情景":
                    out += "\n[%s情景记忆 %s] %s" % (
                        item.get("scene", "?"),
                        item.get("time", "?"),
                        item.get("text", ""),
                    )
            return out
        except Exception:
            return ""

    def _ctx_graph(self, user_input: str) -> str:
        try:
            kg = self.trunk.modules.get("knowledge_graph")
            if not kg:
                return ""
            r = kg.rag_query(user_input)
            return ("\n[知识] " + str(r)[:200]) if r else ""
        except Exception:
            return ""

    _NET_HINTS = (
        "查一下", "搜一下", "搜索", "最新", "新闻", "今天", "天气", "下雨",
        "气温", "几度", "预报", "价格", "多少钱", "行情", "怎么", "教程",
        "官网", "知乎", "B站", "b站", "GitHub", "github", "百度", "下载",
        "是什么", "有哪些", "推荐", "对比", "区别", "热点", "排名",
    )

    def _web_search(self, user_input: str) -> str:
        try:
            if not self.trunk.config.get("联网", True):
                return ""
            q = user_input.strip()
            hits = [w for w in self._NET_HINTS if w in q]
            if not (hits and len(q) <= 120):
                return ""
            ds = self.trunk._load_lazy("deep_search")
            if not ds:
                return ""
            web = ds.search(q)
            if web and str(web).strip():
                self.trunk._log(f"联网搜索: {q[:40]} -> {str(web)[:60]}")
                return "\n[联网] " + str(web)[:800]
        except Exception as e:
            self.trunk._log(f"联网搜索失败: {e}")
        return ""

    def _tool_call(self, user_input: str, is_simple: bool) -> str:
        try:
            if is_simple or not self.trunk.config.get("工具调用", True):
                return ""
            tc = self.trunk._load_lazy("tool_caller")
            if not tc:
                return ""
            tr = tc.call_tools(user_input)
            if tr.get("用工具") != "无":
                self.trunk._log(f"工具自动调用: {user_input[:30]} -> {tr.get('用工具')}")
                return "\n[工具结果] " + str(tr.get("结果", ""))[:600]
        except Exception as e:
            self.trunk._log(f"工具调用失败: {e}")
        return ""

    def build(self, user_input: str, is_simple: bool) -> str:
        context = ""
        if not is_simple:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                    futs = [
                        ex.submit(self._ctx_vector, user_input),
                        ex.submit(self._ctx_memory, user_input),
                        ex.submit(self._ctx_graph, user_input),
                    ]
                    for f in futs:
                        try:
                            context += f.result(timeout=12)
                        except Exception:
                            pass
            except Exception as e:
                self.trunk._log(f"并行检索失败: {e}")
        context += self._web_search(user_input)
        context += self._tool_call(user_input, is_simple)
        return context
