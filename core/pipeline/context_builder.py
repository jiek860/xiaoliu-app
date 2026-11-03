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

from core.data_paths import data_path, data_dir
from core.pipeline.web_context import (clean_query, empty_note, local_hint,
                                       pick_rows, render_rows)


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
        """影子日志路径：跟随 ``trunk.data_dir``，不是 ``trunk.base``。

        坑（2026-11-01 实测）：原来只看 ``base`` —— 测试把 ``data_dir``
        改到临时目录，这个文件却仍写进**真实** data/。于是 983 行里混进了
        「我的猫叫豆豆」「第 1 轮提问」这类测试对话，真实轮次读到的近期
        话题/意图分布被带偏。统一走 ``core.data_paths``。
        """
        return data_path(self.trunk, "chat_shadow.jsonl")

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

    def _vector_hits(self, user_input: str) -> list:
        """向量检索命中的原始条目（结构化，交给 rerank）。"""
        try:
            vs = self.trunk.modules.get("vector_store")
            if vs is None:
                # 批次 D11：库真的存在才懒加载，冷启动不白起一个嵌入线程。
                if os.path.exists(data_path(self.trunk, "vectors.db")):
                    self.trunk._load_lazy("vector_store")
                    vs = self.trunk.modules.get("vector_store")
            if not vs:
                return []
            tk = self.trunk.rule("检索.top_k",
                                 self.trunk.config.get("retrieval_top_k", 3))
            rs = vs.search(user_input, top_k=tk) or []
            out = []
            for r in rs:
                if not isinstance(r, dict):
                    continue
                text = str(r.get("text") or "")
                if not text:
                    continue
                out.append({"text": text,
                            "source": str(r.get("source") or "知识库"),
                            "score": r.get("score", 0)})
            return out
        except Exception:
            return []

    def _ctx_vector(self, user_input: str) -> str:
        return "\n".join(str(r.get("text") or "")[:100]
                         for r in self._vector_hits(user_input))

    # ============ 记忆 v2（批次 43.1 / 第 4 批 A2）============
    #
    # 第 4 批把两件事分开：
    #   * `记忆.注入`（总开关，默认 True）——关掉就完全不注入记忆，只看旧情景记忆；
    #   * `记忆.v2`（实现开关，默认 on）——on 用 v2 记忆卡替换旧情景记忆，
    #     shadow 只记录"本来会注入什么"，off 完全走旧入口。
    # 任何异常都回落到旧结果，绝不因为记忆让回复挂掉。
    def memory_inject_on(self):
        """记忆注入总开关（`记忆.注入`，默认 True）。"""
        try:
            return bool(self.trunk.rule("记忆.注入", True))
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_inject_on")
            return True

    def source_cite_on(self):
        """来源引用开关（`记忆.来源引用`，默认 True）。"""
        try:
            return bool(self.trunk.rule("记忆.来源引用", True))
        except Exception as e:
            _x6_swallowed(__name__, e, "source_cite_on")
            return True

    def memory_mode(self):
        """记忆实现：off / shadow / on（`记忆.v2`，第 4 批起默认 on）。"""
        try:
            value = self.trunk.rule("记忆.v2", "on")
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_mode")
            value = "on"
        if isinstance(value, bool):
            return "on" if value else "off"
        value = str(value or "").strip().lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _memory_rule_int(self, key, default):
        try:
            return max(0, int(self.trunk.rule(key, default)))
        except (TypeError, ValueError):
            return int(default)

    def _mdir(self):
        """记忆卡落盘目录：跟随 ``trunk.data_dir``（见 ``core.data_paths``）。"""
        return data_dir(self.trunk)

    def _recall_memory(self, user_input: str) -> dict:
        """按 `记忆.注入` / `记忆.v2` 决定本轮注入什么。

        返回 ``{kind, items, text}``：
        * ``items`` 是结构化条目（给 rerank 用，每条 ``{text, source, score}``）；
        * ``text`` 是旧拼接入口用的文本（legacy 自带 ``\n[情景记忆…]`` 前缀，
          v2 是 ``【记忆】…`` 行）；
        * ``kind`` 用来区分两套格式，避免 ``_ctx_memory`` 重复加前缀。

        顺带把原来"先算 legacy 再算 v2"的顺序反过来：v2 真能给出内容时
        不再白跑一次可能很慢的 ``memory_loop.recall``（实测最坏 45 秒）。
        """
        def _legacy():
            text = self._ctx_memory_legacy(user_input) or ""
            items = ([{"text": text.strip(), "source": "记忆", "score": 0.6}]
                     if text.strip() else [])
            return {"kind": "legacy", "items": items, "text": text}

        if not self.memory_inject_on():
            return _legacy()
        mode = self.memory_mode()
        if mode == "off":
            return _legacy()
        try:
            from core.chat.memory_v2 import MemoryV2
            base = getattr(self.trunk, "base", ".") or "."
            mv = MemoryV2(base, data_dir=self._mdir())
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
                                        "preview": text[:200]})
                return _legacy()
            if not cards:
                return _legacy()
            mv.commit(cards)             # 只有真正注入才记 24h 去重
            values = dict(getattr(mv, "last_scores", []) or [])
            items = [{"text": str(card.get("text") or ""), "source": "记忆",
                      "score": float(values.get(card.get("id"), 0.0))}
                     for card in cards]
            return {"kind": "v2", "items": items, "text": text}
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_v2")
            return _legacy()

    def _ctx_memory(self, user_input: str) -> str:
        got = self._recall_memory(user_input)
        text = got.get("text") or ""
        if not text:
            return ""
        return text if got.get("kind") == "legacy" else "\n" + text

    def _memory_items(self, user_input: str) -> list:
        """记忆类结构化条目（`_ctx_memory` 的 rerank 版本）。"""
        return list(self._recall_memory(user_input).get("items") or [])

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

    def _graph_item(self, user_input: str):
        """知识图谱命中（结构化条目）；没有图谱或没命中返回 None。"""
        try:
            kg = self.trunk.modules.get("knowledge_graph")
            if not kg:
                return None
            r = kg.rag_query(user_input)
            text = str(r)[:200] if r else ""
            if not text:
                return None
            return {"text": text, "source": "知识图谱", "score": 0.5}
        except Exception:
            return None

    def _ctx_graph(self, user_input: str) -> str:
        item = self._graph_item(user_input)
        return ("\n[知识] " + item["text"]) if item else ""

    _NET_HINTS = (
        "查一下", "搜一下", "搜索", "最新", "新闻", "今天", "天气", "下雨",
        "气温", "几度", "预报", "价格", "多少钱", "行情", "怎么", "教程",
        "官网", "知乎", "B站", "b站", "GitHub", "github", "百度", "下载",
        "是什么", "有哪些", "推荐", "对比", "区别", "热点", "排名",
    )

    def _web_search(self, user_input: str) -> str:
        """联网搜索进上下文。清洗/渲染/说明都在 `core.pipeline.web_context`。

        原来这里是 `str(web)[:4000]` 直接塞 dict 字面量，空结果也算"非空"，
        模型只能反问或许空诺 —— 见 `web_context` 的模块注释。
        """
        try:
            if not self.needs_web(user_input):     # 判据见 needs_web
                return ""
            q = clean_query(user_input)
            ds = self.trunk._load_lazy("deep_search")
            if not ds:
                return empty_note(q, "没装上联网搜索模块")
            rows, summary = pick_rows(ds.search(q))
            self.trunk._log("联网搜索: %s -> %d 条" % (q[:40], len(rows)))
            if not rows:
                return empty_note(q, "引擎没返回任何结果")
            note = local_hint(user_input)
            return render_rows(q, rows, summary) + ("\n" + note if note else "")
        except Exception as e:
            self.trunk._log(f"联网搜索失败: {e}")
        return ""

    # 搜索词清洗：薄壳，逻辑在 web_context.clean_query（测试/外部按方法名调）
    clean_query = staticmethod(clean_query)

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

    def _bounded(self, fn, budget, what, fallback=""):
        """在一棵受控的线程里跑 fn，超过 budget 秒就放弃（线程留着跑完，不阻塞回复）

        注意不能用 `with ThreadPoolExecutor(...)` 来限时：
        它的 __exit__ 会 join 所有线程，超时形同虚设
        （实测 memory 那个任务要 45 秒，build() 就真的等了 45 秒）。

        ``fallback`` 是超时/失败时要还给调用方的内容。原来固定返回 ``""`` ——
        模型因此**根本不知道"这次没搜到"**，只好自己编（"请稍等片刻，我马上
        为您查询"）。现在联网那条会把"没搜到"变成一句明确的上下文。
        """
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(fn)
            try:
                return fut.result(timeout=budget)
            except concurrent.futures.TimeoutError:
                self.trunk._log("%s 超过 %d 秒，本次跳过" % (what, budget))
                return fallback
            except Exception:
                return fallback
        finally:
            # 不 wait：让还在跑的线程自己结束，别拖住回复
            ex.shutdown(wait=False)

    # 三路知识（向量 / 记忆 / 图谱）整块共用的预算（秒）。
    _KNOWLEDGE_BUDGET = 6

    def _collect_items(self, user_input: str) -> list:
        """并发收三路结构化条目；整块共用 `_KNOWLEDGE_BUDGET` 秒。

        到点就把已经拿到的那部分用上，没回来的不要了
        （线程留着跑完，用 shutdown(wait=False) 不 join）。
        """
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        items = []
        try:
            futs = [
                ex.submit(self._vector_hits, user_input),
                ex.submit(self._memory_items, user_input),
                ex.submit(self._graph_item, user_input),
            ]
            done, _pending = concurrent.futures.wait(
                futs, timeout=self._KNOWLEDGE_BUDGET)
            for f in futs:                       # 按提交顺序拼，结果稳定
                if f not in done:
                    continue
                try:
                    got = f.result(timeout=0)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    continue
                if isinstance(got, list):
                    items.extend(got)
                elif isinstance(got, dict) and got.get("text"):
                    items.append(got)
        except Exception as e:
            self.trunk._log(f"并行检索失败: {e}")
        finally:
            ex.shutdown(wait=False)
        return items

    def _format_items(self, user_input: str, items: list) -> str:
        """重排 + 排版成 "相关知识：① …（来源：…）"。"""
        rows = [it for it in (items or []) if isinstance(it, dict) and it.get("text")]
        if not rows:
            return ""
        top_k = self._memory_rule_int("检索.rerank_top_k", 5)
        if top_k <= 0:
            return ""
        try:
            from core.pipeline.rerank import format_passages, rerank
            picked = rerank(user_input, rows, top_k=top_k)
            return format_passages(picked, limit=top_k,
                                   show_source=self.source_cite_on())
        except Exception as e:
            _x6_swallowed(__name__, e, "rerank")
            return "\n" + "\n".join(str(it.get("text") or "")[:120]
                                    for it in rows[:top_k])

    def _ctx_knowledge(self, user_input: str) -> str:
        """三路知识合并后的统一上下文块（第 4 批 A2）。"""
        return self._format_items(user_input, self._collect_items(user_input))

    def build(self, user_input: str, is_simple: bool) -> str:
        context = ""
        if not is_simple:
            # 三路检索（向量 / 记忆 / 图谱）→ rerank → "相关知识：① …"。
            # 原来是三路各自 join 文本后硬拼：顺序由提交顺序决定、
            # 同一条偏好可能重复、且丢了来源。现在统一进 rerank。
            context = self._ctx_knowledge(user_input)
        # 联网搜索 和 工具调用 互不依赖，**并行**跑。
        # 原来是串行：各自卡 8 秒和 12 秒上限，加起来最坏 20 秒，
        # 而这两件事没有任何先后关系 —— 并行之后只花最慢那个的时间。
        import concurrent.futures
        # 联网那条超时也要留句话：告诉模型"这次没搜到"，别让它许空诺。
        try:
            wants_web = self.needs_web(user_input)
        except Exception:
            wants_web = False
        web_fallback = ""
        if wants_web:
            web_fallback = empty_note(
                clean_query(user_input), "超过 %d 秒没回来" % self._WEB_BUDGET)
        ex2 = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        try:
            f_web = ex2.submit(self._bounded, lambda: self._web_search(user_input),
                               self._WEB_BUDGET, "联网搜索", web_fallback)
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
