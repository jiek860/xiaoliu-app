from core.untrusted_content import wrap_search_result
# -*- coding: utf-8 -*-
"""上下文构建：并行检索 + 联网搜索 + 工具调用"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import concurrent.futures
import json
import os
import threading
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

    # ============ 影子状态（批次 41.4）============
    #
    # 只记录、不参与回复：给批次 42 的状态层/规划器攒分布数据。
    # 任何写入失败都吞掉（按 diagnostics.swallowed），绝不影响聊天。
    _SHADOW_LOCK = threading.Lock()
    _SHADOW_MAX_BYTES = 2 * 1024 * 1024

    _INTENT_RULES = (
        ("correct", ("不对", "不是这个", "我是说", "你错了", "理解错", "跑题")),
        ("vent", ("烦", "累", "难受", "崩溃", "气死", "焦虑", "睡不着",
                  "不想上班")),
        ("ask_fact", ("是什么", "为什么", "怎么", "多少", "几点", "谁", "哪")),
        ("request_help", ("帮我", "帮忙", "写", "做", "修", "改", "查",
                          "看看")),
        ("smalltalk", ("你好", "在吗", "hi", "hello", "谢谢", "晚安", "早")),
    )

    _TOPIC_RULES = (
        ("代码", ("代码", "报错", "函数", "bug", "pytest", "重构", "接口",
                  "文件", "报错")),
        ("情绪", ("累", "烦", "难受", "焦虑", "开心", "被夸")),
        ("工作", ("上班", "老板", "项目", "周报", "加班")),
        ("生活", ("天气", "吃", "睡", "周末", "电影")),
    )

    def guess_intent(self, user_input: str) -> str:
        """规则版意图，仅用于影子记录与后续规划的兜底。"""
        q = str(user_input or "").strip().lower()
        for name, words in self._INTENT_RULES:
            if any(w.lower() in q for w in words):
                return name
        return "chat"

    def guess_topic(self, user_input: str) -> str:
        q = str(user_input or "")
        for name, words in self._TOPIC_RULES:
            if any(w in q for w in words):
                return name
        return "闲聊"

    def shadow_enabled(self) -> bool:
        try:
            return bool(self.trunk.rule("聊天.影子状态", True))
        except Exception:
            return True

    def shadow_path(self) -> str:
        base = getattr(self.trunk, "base", ".") or "."
        return os.path.join(base, "data", "chat_shadow.jsonl")

    def record_shadow(self, payload: dict) -> bool:
        """追加一行影子状态，返回是否写入成功。"""
        try:
            if not self.shadow_enabled():
                return False
            row = dict(payload or {})
            row.setdefault("ts", round(time.time(), 3))
            path = self.shadow_path()
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with self._SHADOW_LOCK:
                try:
                    if os.path.getsize(path) > self._SHADOW_MAX_BYTES:
                        os.replace(path, path + ".1")
                except OSError:
                    pass
                with open(path, "a", encoding="utf-8") as fp:
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            _x6_swallowed(__name__, e, "shadow_state")
            return False

    # ============ 联网：只在"明确要查外部信息"时才搜 ============
    #
    # 原来是一张很宽的关键词表，里面混着 "怎么" "教程" "今天" "是什么"
    # "有哪些" "推荐" "对比" "区别" —— 这些在日常对话里太常见，
    # 结果「这个怎么用」也会去联网，每次白等几秒还往提示词里塞一堆无关网页。
    # 现在分两档，都要求"用户确实在问外部/时效性的事实"：
    #
    # 「明确要求去搜」单独拆出来 —— 关掉 E 组规则「联网.默认放开」时只认这一档。
    # 原来它和下面那批时效词混在一张表里，于是"关掉自动联网"对"今天天气怎么样"
    # 这种时效提问无效（因为"天气"也在强信号表里）。
    _NET_EXPLICIT = (
        "搜一下", "搜下", "搜索", "查一下", "查下", "帮我查", "帮我搜",
        "百度", "谷歌", "必应", "bing",
    )
    _NET_STRONG = _NET_EXPLICIT + (
        # 明确的时效信号（关掉「联网.默认放开」后不再自动联网）
        "最新", "实时", "现在几点", "今天几号", "股价", "汇率", "油价",
        "天气", "气温", "下雨", "几度", "预报", "新闻", "热点",
        # 明确要外部资源
        "官网", "下载地址", "多少钱", "价格", "报价", "行情", "排行榜",
    )
    # 时间词 + 事实词 同时出现才算（避免"今天心情不好"也去搜）
    _NET_TIME = ("今天", "现在", "目前", "最近", "今年", "这几天", "当前")
    _NET_FACT = ("天气", "新闻", "价格", "股价", "汇率", "赛事", "票房",
                 "版本", "发布会", "政策", "规定", "行情", "温度")

    def _auto_web(self):
        """「联网.默认放开」规则：默认允许自动联网抓取（默认开 = 原来的行为）

        E 组那条规则写着"默认可联网抓取，无需每次询问"。实际现状是：联网确实
        从来不问用户，但**触发很保守**（只有明确要查外部信息才搜）。所以
        True 时保持现状；关掉它就只认"明确要求搜"那一档（_NET_EXPLICIT），
        "天气/新闻/股价"这类时效词不再自动触发联网。
        """
        try:
            if self.trunk:
                return bool(self.trunk.rule("联网.默认放开", True))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return True

    def needs_web(self, user_input: str) -> bool:
        """这次要不要联网。宁可少搜 —— 搜错了不仅慢，还会污染上下文。"""
        try:
            if not self.trunk.config.get("联网", True):
                return False
            q = user_input.strip()
            if not q or len(q) > 100:      # 长文多半是让我分析/写作，不是查事实
                return False
            if any(w in q for w in self._NET_EXPLICIT):
                return True                # 用户明确要求搜 —— 这条始终认
            if not self._auto_web():
                # 关掉「联网.默认放开」：时效词与"时间+事实"弱信号都不再自动联网
                return False
            if any(w in q for w in self._NET_STRONG):
                return True
            if (any(w in q for w in self._NET_TIME)
                    and any(w in q for w in self._NET_FACT)):
                return True
            return False
        except Exception:
            return False

    # ============ 工具调用：先零成本粗筛，命中才去问 LLM ============
    #
    # 原来只要不是"简单消息"就一律走工具调用，而工具调用的第一步是
    # **让云端 LLM 决策一次**（一次完整的往返，实测约 5 秒）。
    # 于是「什么是量子纠缠」这种纯知识问题，也要先花 5 秒让 LLM 回答
    # "不需要工具"，然后才真正开始回答。
    #
    # 现在先看用户有没有"想让它动手"的意思，没有就直接跳过，一次调用都不发。
    # 下面的词对应 tool_caller 实际提供的 7 个工具：
    #   code_run 运行Python / file_read 读文件 / vector_search 搜记忆 /
    #   graph_query 查知识图谱 / task_plan 规划步骤 / computer 控制电脑 /
    #   deep_search（联网那条已经单独判过了）
    _TOOL_HINTS = (
        # 运行代码 / 计算
        "运行", "执行", "跑一下", "跑下", "算一下", "算算", "计算一下", "写个脚本",
        # 读文件
        "读一下", "读读", "读取", "打开文件", "看看这个文件", "文件里",
        # 翻记忆 / 知识库
        "我之前", "我上次", "我说过", "还记得", "记不记得", "我的记录",
        "知识库", "之前学过", "以前说过",
        # 规划
        "帮我规划", "规划一下", "分步骤", "拆解", "制定计划", "列个计划",
        # 电脑操作（快速通道没接住的复杂表述会落到这里）
        "截屏", "截图", "打开", "关闭", "启动",
    )

    def maybe_needs_tools(self, user_input: str) -> bool:
        """这次值不值得问 LLM"要不要用工具"。"""
        try:
            if not self.trunk.config.get("工具调用", True):
                return False
            q = user_input.strip()
            if len(q) < 4:
                return False
            return any(w in q for w in self._TOOL_HINTS)
        except Exception:
            return False

    def _ctx_vector(self, user_input: str) -> str:
        try:
            vs = self.trunk.modules.get("vector_store")
            if vs is None:
                # 批次 D11：库真的存在才懒加载，冷启动不白起一个嵌入线程。
                base = getattr(self.trunk, "base", ".") or "."
                if os.path.exists(os.path.join(base, "data", "vectors.db")):
                    self.trunk._load_lazy("vector_store")
                    vs = self.trunk.modules.get("vector_store")
            if not vs:
                return ""
            tk = self.trunk.rule("检索.top_k",
                                 self.trunk.config.get("retrieval_top_k", 3))
            rs = vs.search(user_input, top_k=tk)
            return "\n".join(r.get("text", "")[:100] for r in rs) if rs else ""
        except Exception:
            return ""

    # ============ 记忆 v2（批次 43.1）============
    #
    # 旧入口（memory_loop 情景）保持不变；`记忆.v2` 默认 shadow：
    # 只把「本来会注入什么」写进影子日志，上下文仍是旧内容。
    # `on` 才用新入口替换，且任何异常都回落到旧结果。
    def memory_mode(self):
        """记忆开关：off / shadow / on（`记忆.v2`，默认 shadow）。"""
        try:
            value = self.trunk.rule("记忆.v2", "shadow")
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_mode")
            value = "shadow"
        if isinstance(value, bool):
            return "on" if value else "off"
        value = str(value or "").strip().lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _memory_rule_int(self, key, default):
        try:
            return max(0, int(self.trunk.rule(key, default)))
        except (TypeError, ValueError):
            return int(default)

    def _ctx_memory(self, user_input: str) -> str:
        legacy = self._ctx_memory_legacy(user_input)
        mode = self.memory_mode()
        if mode == "off":
            return legacy
        try:
            from core.chat.memory_v2 import MemoryV2
            base = getattr(self.trunk, "base", ".") or "."
            mv = MemoryV2(base)
            cards = mv.recall(
                user_input,
                topic=self.guess_topic(user_input),
                limit=self._memory_rule_int("记忆.注入张数", 3),
                max_chars=self._memory_rule_int("记忆.注入字数", 200),
                hours=self._memory_rule_int("记忆.去重小时", 24),
            )
            text = mv.render(cards)
            if mode == "shadow":
                if text:
                    self.record_shadow({"kind": "memory_v2",
                                        "count": len(cards),
                                        "v2_chars": len(text),
                                        "legacy_chars": len(legacy or ""),
                                        "preview": text[:200]})
                return legacy
            if text:
                mv.commit(cards)         # 只有真正注入才记 24h 去重
                return "\n" + text
            return legacy
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_v2")
            return legacy

    def _ctx_memory_legacy(self, user_input: str) -> str:
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
            if not self.needs_web(user_input):     # 判据见 needs_web
                return ""
            q = user_input.strip()
            ds = self.trunk._load_lazy("deep_search")
            if not ds:
                return ""
            web = ds.search(q)
            if web and str(web).strip():
                self.trunk._log(f"联网搜索: {q[:40]} -> {str(web)[:60]}")
                return "\n[联网-不可信资料] " + wrap_search_result(str(web)[:4000], source="web_search")
        except Exception as e:
            self.trunk._log(f"联网搜索失败: {e}")
        return ""

    def _tool_call(self, user_input: str, is_simple: bool) -> str:
        try:
            if is_simple or not self.maybe_needs_tools(user_input):
                # 粗筛没过就直接跳过 —— 一次 LLM 调用都不发。
                # 原来这里只要不是"简单消息"就一律进，于是纯知识问答
                # 也要先花约 5 秒让云端 LLM 回答"不需要工具"。
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
            # 三个检索并行跑，**整块共用一个 6 秒预算**。
            # 原来是对每个 future 各给 6 秒（f.result(timeout=6)），
            # 三个加起来最坏 18 秒 —— 实测纯知识问题在检索上白花 10 秒。
            # 现在用 wait(timeout=6) 统一计时，到点就把已经拿到的那部分用上，
            # 没回来的不要了（线程留着跑完，用 shutdown(wait=False) 不 join）。
            import concurrent.futures
            ex = concurrent.futures.ThreadPoolExecutor(max_workers=3)
            try:
                futs = [
                    ex.submit(self._ctx_vector, user_input),
                    ex.submit(self._ctx_memory, user_input),
                    ex.submit(self._ctx_graph, user_input),
                ]
                done, _pending = concurrent.futures.wait(futs, timeout=6)
                for f in futs:                       # 按提交顺序拼，结果稳定
                    if f in done:
                        try:
                            context += f.result(timeout=0)
                        except Exception as e:
                            _x6_swallowed(__name__, e)
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
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        finally:
            ex2.shutdown(wait=False)
        return context
