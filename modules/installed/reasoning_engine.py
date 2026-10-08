# -*- coding: utf-8 -*-
"""推理引擎 v2.1 - 多步推理 + 思维链 + 历史记录 + 清空 + 统计 + 导出"""
import sys, os, time
from core.safe import safe
from modules.base import BaseModule


class ReasoningEngine(BaseModule):
    NAME = "reasoning_engine"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.history = []
        self.reason_count = 0

    @safe
    def think(self, question):
        """多步推理"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}

        steps = []

        # 第一步：分解问题
        try:
            r1 = llm.chat(f"把这个问题拆成2-3个小步骤:\n{question[:200]}")
            steps.append({"步骤": 1, "内容": r1[:150]})
        except: pass

        # 第二步：逐步解决
        try:
            r2 = llm.chat(f"逐步解决:\n{steps[0]['内容'] if steps else question[:100]}")
            steps.append({"步骤": 2, "内容": r2[:150]})
        except: pass

        # 第三步：总结
        try:
            r3 = llm.chat(f"总结答案:\n{r2[:200] if steps else ''}")
            steps.append({"步骤": 3, "内容": r3[:150]})
        except: pass

        # 记录历史
        self.reason_count += 1
        self.history.append({
            "问题": question[:50],
            "步骤数": len(steps),
            "时间": time.strftime("%m-%d %H:%M")
        })
        if len(self.history) > 30:
            self.history = self.history[-30:]

        return {"问题": question, "推理步骤": steps, "结论": steps[-1]["内容"] if steps else ""}

    @safe
    def chain_of_thought(self, question):
        """思维链推理"""
        return self.think(question)

    @safe
    def compare_answers(self, question, answers):
        """比较多个答案"""
        llm = self.trunk.modules.get("llm")
        if not llm:
            return {"错误": "LLM未加载"}
        try:
            r = llm.chat(f"比较这些答案哪个最好:\n{answers}\n问题: {question}")
            return {"比较结果": r}
        except Exception as e:
            return {"错误": str(e)[:80]}

    @safe
    def get_history(self, count=10):
        """获取推理历史"""
        return {"历史": self.history[-count:]}

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        self.reason_count = 0
        return {"ok": True}

    @safe
    def stats(self):
        """统计"""
        return {
            "总推理次数": self.reason_count,
            "历史数": len(self.history)
        }

    @safe
    def export_report(self):
        """导出报告"""
        s = self.stats()
        report = f"""推理引擎报告
==========
总推理次数: {s['总推理次数']}
历史数: {s['历史数']}
"""
        return {"报告": report}

    def run(self, *args):
        if args:
            return self.think(args[0])
        return self.stats()
