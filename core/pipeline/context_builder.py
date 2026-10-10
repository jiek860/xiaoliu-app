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

    # 联网搜索 / 工具调用各自的总时限（秒）。
    # 这两步是串行的且原来完全没有上限：实测联网搜索最坏 3 个引擎各 6 秒
    # 再加一次 LLM 总结 ≈ 14 秒；工具调用要先让 LLM 决策、再执行工具
    # （工具里又可能含向量检索和联网搜索）≈ 58 秒。
    # 回复前的"准备"不该比生成还慢，所以各自卡一个上限，超了就放弃这部分上下文。
    _WEB_BUDGET = 8
    _TOOL_BUDGET = 12

    def _bounded(self, fn, budget, what):
        """在一棵受控的线程里跑 fn，超过 budget 秒就放弃（线程留着跑完，不阻塞回复）

        注意不能用 `with ThreadPoolExecutor(...)` 来限时：
        它的 __exit__ 会 join 所有线程，超时形同虚设
        （实测 memory 那个任务要 45 秒，build() 就真的等了 45 秒）。
        """
        import concurrent.futures
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(fn)
            try:
                return fut.result(timeout=budget)
            except concurrent.futures.TimeoutError:
                self.trunk._log("%s 超过 %d 秒，本次跳过" % (what, budget))
                return ""
            except Exception:
                return ""
        finally:
            # 不 wait：让还在跑的线程自己结束，别拖住回复
            ex.shutdown(wait=False)

    def build(self, user_input: str, is_simple: bool) -> str:
        context = ""
        if not is_simple:
            # 三个检索并行跑，每个单独限时；用 shutdown(wait=False) 而不是 with，
            # 否则退出时会 join，慢的那个会把整个 build 拖住。
            import concurrent.futures
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=3)
            try:
                futs = [
                    ex.submit(self._ctx_vector, user_input),
                    ex.submit(self._ctx_memory, user_input),
                    ex.submit(self._ctx_graph, user_input),
                ]
                for f in futs:
                    try:
                        context += f.result(timeout=6)
                    except Exception:
                        pass
            except Exception as e:
                self.trunk._log(f"并行检索失败: {e}")
            finally:
                ex.shutdown(wait=False)
        # 联网搜索 和 工具调用 互不依赖，**并行**跑。
        # 原来是串行：各自卡 8 秒和 12 秒上限，加起来最坏 20 秒，
        # 而这两件事没有任何先后关系 —— 并行之后只花最慢那个的时间。
        import concurrent.futures
        ex2 = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            f_web = ex2.submit(self._bounded, lambda: self._web_search(user_input),
                               self._WEB_BUDGET, "联网搜索")
            f_tool = ex2.submit(self._bounded, lambda: self._tool_call(user_input, is_simple),
                                self._TOOL_BUDGET, "工具调用")
            for f in (f_web, f_tool):
                try:
                    context += f.result(timeout=max(self._WEB_BUDGET,
                                                    self._TOOL_BUDGET) + 2)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            ex2.shutdown(wait=False)
        return context
