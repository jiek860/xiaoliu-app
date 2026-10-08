# -*- coding: utf-8 -*-
"""通用子智能体基类：三个agent共用逻辑"""
class AgentGeneric:
    ROLE = "通用"
    SYSTEM_PROMPT = "你是一个通用助手。"
    def __init__(self, trunk=None):
        self.trunk = trunk
    def reply(self, question):
        try:
            llm = self.trunk.modules.get("llm") if self.trunk else None
            if not llm:
                return "（LLM未加载）"
            return llm.chat([
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": str(question)[:500]},
            ])
        except Exception as e:
            return "（智能体出错: %s）" % str(e)[:60]
    def run(self, *a):
        return self.reply(a[0] if a else "")
