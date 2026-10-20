# -*- coding: utf-8 -*-
"""编程小匠 - 复用AgentGeneric"""
from core.agent_generic import AgentGeneric
class AgentCoder(AgentGeneric):
    ROLE = "编程小匠"
    SYSTEM_PROMPT = "你是编程小匠，只回答编程/技术问题，给最小可用代码。"
