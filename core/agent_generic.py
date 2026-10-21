# -*- coding: utf-8 -*-
"""通用子智能体基类：三个 agent 共用逻辑。

不负责：模型选择、记忆写入、工具调用编排（这些由 trunk / reply 管道负责）。
"""
try:
    from modules.base import BaseModule as _Base
except ImportError:  # 独立加载时保持可用
    _Base = object


class AgentGeneric(_Base):
    """通用子智能体基类。

    历史问题（2026-10-21 由插件质量门禁发现）：
    本类原来不继承 ``BaseModule``，于是 ``agent_analyst`` / ``agent_coder`` /
    ``agent_planner`` 虽然能用，却**不符合模块标准 1.2（入口 run）与
    4.1（生命周期）**——质量门禁直接报 error。现在继承基类即可全部满足。
    """

    NAME = "agent_generic"
    VERSION = "1.0"
    ROLE = "通用"
    SYSTEM_PROMPT = "你是一个通用助手。"
    NOT_RESPONSIBLE = ("模型选择", "记忆写入", "工具编排")

    def __init__(self, trunk=None):
        try:
            super().__init__(trunk)
        except TypeError:
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
