# -*- coding: utf-8 -*-
"""分析专家 - 复用AgentGeneric"""
from core.agent_generic import AgentGeneric
class AgentAnalyst(AgentGeneric):
    ROLE = "分析专家"
    SYSTEM_PROMPT = "你是分析专家，理性分点，指出利弊和风险。"
