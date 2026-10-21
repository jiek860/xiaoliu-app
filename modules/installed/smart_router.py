# -*- coding: utf-8 -*-
"""
import os智能路由 v10.0 - LLM真意图识别+路由缓存+反馈学习+置信度阈值"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import re, json, os
from modules.base import BaseModule

class SmartRouter(BaseModule):
    NAME = "smart_router"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            self.conf_threshold = self.trunk.rule("路由.conf_threshold", 0.6)  # C1: LLM 置信度下限
        except Exception:
            self.conf_threshold = 0.6
        self.cache = {}  # {问题: 路由结果}
        self.weights = {}  # {意图: 权重，反馈学习}
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        _sdir = os.path.join(self.base, "data", "plugin_data", "smart_router")
        os.makedirs(_sdir, exist_ok=True)
        self.cache_path = os.path.join(_sdir, "router_cache.json")
        _legacy = os.path.join(self.base, "data", "router_cache.json")
        if not os.path.exists(self.cache_path) and os.path.exists(_legacy):
            try: os.replace(_legacy, self.cache_path)
            except OSError:  # 静默是故意的：旧数据迁移失败不阻断主流程
                pass
        if os.path.exists(self.cache_path):
            try: self.cache = json.load(open(self.cache_path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
        # 意图→模块映射
        self.intents = {
            "code": "agent_coder",
            "analysis": "agent_analyst",
            "planner": "agent_planner",
            "search": "deep_search",
            "task": "task_loop",  # 复杂任务 → 任务闭环（拆步+执行+沙盒验证）
            "tool": "tool_caller",
            "reflect": "self_reflect",
            "emotion": "empathy",
            "greet": None,  # 直接聊天
        }

    def _kw_fallback(self, text):
        """LLM 判断失败/低置信时用关键词分数兜底，避免无脑回 greet"""
        try:
            kw_map = {
                "code": ["代码","编程","python","bug","函数","写一个","接口","脚本","实现"],
                "analysis": ["分析","总结","对比","为什么","原因","数据","优缺点"],
                "planner": ["规划","方案","计划","路线图","创意","设计","策划"],
                "search": ["搜索","最新","新闻","查一下","百度","实时"],
                "task": ["任务","拆","怎么做","帮我做","执行"],
            }
            best, best_n = "greet", 0
            for intent, kws in kw_map.items():
                n = sum(1 for k in kws if k in text)
                if n > best_n:
                    best, best_n = intent, n
            return best, (0.6 if best_n else 0.0)
        except Exception:
            return "greet", 0.0

    def _llm_route(self, text):
        """v10.1(C1): LLM真判断意图 + 置信度，低于阈值回主 LLM"""
        llm = self.trunk.modules.get("llm")
        if not llm: return "greet", 0.0
        prompt = f"""你是智能路由，判断下面的用户问题该交给哪个方向回答。
只输出一行：意图 置信度(0-1)。意图只能是 code / analysis / planner / search / task / greet 之一。
code=编程写代码；analysis=分析总结；planner=策划方案；search=联网搜索；task=执行任务；greet=闲聊日常。
问题：{text[:100]}
示例输出：code 0.9
只输出一行："""
        try:
            r = llm.chat(prompt).strip().lower()
        except Exception:
            return self._kw_fallback(text)
        # 解析：支持 "code 0.9" / "code:0.9" / "code,0.9" / "意图:code 置信度:0.9"
        r2 = re.sub(r"[：:]", " ", r)
        parts = r2.split()
        intent = parts[0] if parts else "greet"
        conf = 0.6
        for tok in parts[1:]:
            try:
                conf = max(0.0, min(1.0, float(tok)))
                break
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
        # 意图词必须是合法意图之一（防止 LLM 输出别的词）
        hit = next((k for k in self.intents if k == intent), None)
        if hit is None:
            # 输出里可能带 "code" 被误拼，做包含匹配
            hit = next((k for k in self.intents if k in intent), None)
        if hit is None:
            return self._kw_fallback(text)
        if conf < self.conf_threshold:
            return self._kw_fallback(text)  # 低置信 → 关键词兜底，不直接 greet
        return hit, conf

    def route(self, text):
        """v10: 缓存→关键词→LLM→缓存写回"""
        # 1. 查缓存
        if text in self.cache:
            return self.cache[text]
        # 2. 关键词快速判断
        kw_scores = {}
        kw_map = {
            "code": ["代码","编程","python","bug","函数","写一个","接口"],
            "analysis": ["分析","总结","对比","为什么","原因","数据"],
            "planner": ["规划","方案","计划","路线图","创意","设计"],
            "search": ["搜索","最新","新闻","查一下","百度","搜一下","实时"],
            "task": ["任务","拆","怎么做","帮我做","计划"],
        }
        for intent, kws in kw_map.items():
            score = sum(1 for k in kws if k in text)
            if score > 0: kw_scores[intent] = score
        # 3. 关键词命中（≥1 且最高分唯一）→ 直接走，不依赖弱 LLM
        top_score = max(kw_scores.values()) if kw_scores else 0
        top_intents = [k for k, v in kw_scores.items() if v == top_score]
        if kw_scores and top_score >= 1 and len(top_intents) == 1:
            intent = top_intents[0]
            result = {"意图": intent, "模块": self.intents[intent], "置信度": "关键词", "方法": "keyword"}
        else:
            # 4. LLM判断（带置信度）；失败/低置信由 _kw_fallback 兜底
            intent, conf = self._llm_route(text)
            result = {"意图": intent, "模块": self.intents.get(intent),
                      "置信度": conf, "方法": "llm" if conf else "keyword"}
        # 5. 写缓存——只有关键词确定性结果才落盘
        #    （LLM 判断结果不写缓存，避免 LLM 降级/失败时的错误结果被固化，路由假死）
        if result.get("方法") == "keyword":
            self.cache[text] = result
            if len(self.cache) > 500:
                self.cache = dict(list(self.cache.items())[-200:])
            try: from core.safe import atomic_write_json; atomic_write_json(self.cache_path, self.cache, indent=None)
            except Exception as e:
                _x6_swallowed(__name__, e)
        return result

    def feedback(self, text, correct_intent):
        """v10: 用户反馈学习——纠正后调整"""
        self.weights[correct_intent] = self.weights.get(correct_intent, 1.0) + 0.1
        if text in self.cache:
            del self.cache[text]

    def run(self, *args):
        return self.route(args[0] if args else "")

