# -*- coding: utf-8 -*-
"""策划专家 - 复用AgentGeneric"""
from core.agent_generic import AgentGeneric
class AgentPlanner(AgentGeneric):
    ROLE = "策划专家"
    SYSTEM_PROMPT = "你是策划专家，擅长拆解目标为可执行步骤，给方案和备选。"
