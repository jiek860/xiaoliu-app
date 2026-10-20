# -*- coding: utf-8 -*-
"""自我反思 v2.1 - LLM打分 + 规则粗筛 + 历史记录 + 改进建议 + 清空 + 统计

v2.1 修的是"分数会说谎"：
  · reflect() 原来 LLM 挂了就 except: pass，照样记一个"5 分"；
  · quick_eval() 原来给**所有正常回答**打基线 5 分；
  · 两者共用一份 history，且没有来源标记。
  实测 data/reflect_history.json 50 条里 48 条是这种假 5 分，
  于是 average_score 被灌水、worst_answers 排名失真、get_advice 恒返回空
  （它要求"有建议"，而规则那条永远没有建议）。
  现在：没评上就留空并写明原因，两种来源分别标记，统计只算真正评过分的。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, time, json, re
from core.safe import safe
from modules.base import BaseModule


class ReflectEngine(BaseModule):
    NAME = "self_reflect"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.history_path = os.path.join(self.base, "data", "reflect_history.json")
        self.history = self._load()
        self.reflect_count = 0

    def _load(self):
        if os.path.exists(self.history_path):
            try:
                return json.load(open(self.history_path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
        return []

    def _save(self):
        try:
            json.dump(self.history, open(self.history_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _scored(self):
        """真正被评过分的条目（分数可能是 None —— 规则粗筛的"无意见"和没评上的）"""
        return [h for h in self.history
                if isinstance(h.get("分数"), (int, float))]

    @safe
    def reflect(self, user_input, ai_response):
        """自我反思：让模型打分 + 一句改进点

        评分要靠 LLM。它不可用、或答非所问（没吐出数字）时**不能**悄悄记一个
        "5 分" —— 那会让数据看起来像"每条都是中等评价"，把下游统计全带偏。
        评不上就如实留空，并写明原因。
        """
        llm = self.trunk.modules.get("llm") if self.trunk else None
        score, suggestion, err = None, "", ""

        if not llm:
            err = "LLM 未就绪"
        else:
            try:
                prompt = ("用户问：%s\n我答：%s\n这个回答打几分(1-10)？一句话说改进点:"
                          % (str(user_input)[:100], str(ai_response)[:200]))
                r = str(llm.chat(prompt) or "")
                m = re.search(r"(\d+)", r)
                if m:
                    score = max(1, min(10, int(m.group(1))))
                else:
                    err = "模型没给出分数"
                suggestion = r[:100]
            except Exception as e:
                err = "调用模型失败: %s" % str(e)[:60]

        entry = {
            "用户": str(user_input)[:50],
            "回答": str(ai_response)[:50],
            "分数": score,
            "建议": suggestion,
            "时间": time.strftime("%m-%d %H:%M"),
            "来源": "模型",
        }
        if err:
            entry["未评分"] = err
        self.history.append(entry)
        self.reflect_count += 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()

        if err and self.trunk:
            try:
                self.trunk._log("自我反思未评分: %s" % err, "WARN")
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return {"分数": score, "建议": suggestion, "未评分": err or None}

    @safe
    def get_history(self, count=10):
        """获取反思历史"""
        return {"历史": self.history[-count:]}

    @safe
    def worst_answers(self, n=5):
        """获取最差的回答（只从真正评过分的里挑，规则粗筛的"无意见"不算）"""
        scored = self._scored()
        if not scored:
            return []
        return sorted(scored, key=lambda x: x["分数"])[:n]

    @safe
    def average_score(self):
        """平均分：只算真正被评过分的条目。

        规则的"无意见"(分数 None) 和没评上的模型条目都不参与 ——
        原来把基线 5 分也算进去，等于往平均分里灌水。
        """
        scored = [h["分数"] for h in self._scored()]
        if not scored:
            return 0
        return sum(scored) / len(scored)

    @safe
    def get_advice(self):
        """取最近低分反思的教训，注入下次 prompt

        只认「有建议」的条目。规则粗筛那条永远没有建议，掺进来只会让它恒返回空
        —— 原来 50 条里 48 条是这种，所以这个功能实际上从没生效过。
        """
        if not self.history:
            return ""
        cand = [h for h in self.history[-20:]
                if str(h.get("建议") or "").strip()
                and isinstance(h.get("分数"), (int, float))]
        if not cand:
            return ""
        worst = min(cand, key=lambda x: x["分数"])
        if worst["分数"] < 6:
            return str(worst["建议"])[:80]
        return ""

    @safe
    def quick_eval(self, user_input, ai_response):
        """规则粗筛，不调模型（省 Ollama 排队）

        它**不是评分**，只干一件事：把明显不对的回答挑出来。
        所以正常回答记「分数: None（无意见）」而不是一个基线 5 分 ——
        原来给所有正常回答打 5 分，等于往统计里灌水：实测 50 条里 48 条是
        这种假分，average_score 和 worst_answers 全被带偏。
        """
        text = str(ai_response or "")
        score, why = None, ""
        if len(text) < 5:
            score, why = 3, "回答太短"
        elif text.startswith(("（抱歉", "本地模型错误", "（模型错误")):
            score, why = 1, "错误占位"
        elif len(text) > 3000:
            score, why = 4, "回答过长"

        entry = {
            "用户": str(user_input)[:50],
            "回答": text[:50],
            "分数": score,
            "建议": "",
            "时间": time.strftime("%m-%d %H:%M"),
            "来源": "规则",
        }
        if why:
            entry["问题"] = why
        self.history.append(entry)
        self.reflect_count += 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()
        return {"分数": score, "问题": why or None}

    @safe
    def stats(self):
        """统计"""
        scored = self._scored()
        return {
            "总反思次数": self.reflect_count,
            "平均分": round(self.average_score(), 2),
            "历史数": len(self.history),
            "已评分": len(scored),
        }

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.reflect_count = 0
        self._save()
        return {"ok": True}

    def run(self, *args):
        return self.stats()

