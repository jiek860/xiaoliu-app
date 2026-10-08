# -*- coding: utf-8 -*-
"""自我反思 v2.0 - LLM打分 + 历史记录 + 改进建议 + 清空 + 统计"""
import sys, os, time, json
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
            except: pass
        return []

    def _save(self):
        try:
            json.dump(self.history, open(self.history_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except: pass

    @safe
    def reflect(self, user_input, ai_response):
        """自我反思"""
        llm = self.trunk.modules.get("llm")
        score = 5  # 默认分
        suggestion = ""

        if llm:
            try:
                prompt = f"用户问：{user_input[:100]}\n我答：{ai_response[:200]}\n这个回答打几分(1-10)？一句话说改进点:"
                r = llm.chat(prompt)
                # 提取分数
                import re
                m = re.search(r"(\d+)", r)
                if m:
                    score = int(m.group(1))
                suggestion = r[:100]
            except: pass

        # 记录历史
        entry = {
            "用户": user_input[:50],
            "回答": ai_response[:50],
            "分数": score,
            "建议": suggestion,
            "时间": time.strftime("%m-%d %H:%M")
        }
        self.history.append(entry)
        self.reflect_count += 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()

        return {"分数": score, "建议": suggestion}

    @safe
    def get_history(self, count=10):
        """获取反思历史"""
        return {"历史": self.history[-count:]}

    @safe
    def worst_answers(self, n=5):
        """获取最差的回答"""
        if not self.history:
            return []
        sorted_h = sorted(self.history, key=lambda x: x["分数"])
        return sorted_h[:n]

    @safe
    def average_score(self):
        """平均分"""
        if not self.history:
            return 0
        return sum(h["分数"] for h in self.history) / len(self.history)

    @safe
    def get_advice(self):
        """取最近低分反思的教训，注入下次 prompt"""
        if not self.history:
            return ""
        recent = self.history[-10:]
        worst = min(recent, key=lambda x: x.get("分数", 10))
        if worst.get("分数", 10) < 6 and worst.get("建议"):
            return str(worst["建议"])[:80]
        return ""

    @safe
    def quick_eval(self, user_input, ai_response):
        """规则打分，不调模型（省 Ollama 排队）"""
        score = 5
        n = len(str(ai_response or ""))
        if n < 5:
            score -= 2
        elif n > 3000:
            score -= 1
        if str(ai_response).startswith(("（抱歉", "本地模型错误", "（模型错误")):
            score = 1
        entry = {
            "用户": str(user_input)[:50],
            "回答": str(ai_response)[:50],
            "分数": score,
            "建议": "",
            "时间": time.strftime("%m-%d %H:%M"),
        }
        self.history.append(entry)
        self.reflect_count += 1
        if len(self.history) > 50:
            self.history = self.history[-50:]
        self._save()
        return {"分数": score}

    @safe
    def stats(self):
        """统计"""
        return {
            "总反思次数": self.reflect_count,
            "平均分": round(self.average_score(), 2),
            "历史数": len(self.history)
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

