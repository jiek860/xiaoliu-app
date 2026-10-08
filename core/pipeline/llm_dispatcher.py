# -*- coding: utf-8 -*-
"""LLM 调度：流式优先，失败降级非流式"""
class LLMDispatcher:
    def __init__(self, trunk):
        self.trunk = trunk

    def dispatch(self, messages: list, on_token=None) -> str:
        llm = self.trunk.modules.get("llm")
        if not llm:
            return "LLM未初始化"
        if on_token and hasattr(llm, "stream_chat"):
            answer = llm.stream_chat(messages, on_token=on_token)
            if not answer or str(answer).startswith(("（模型错误", "本地模型错误")):
                answer = llm.chat(messages)
                if on_token and answer:
                    on_token(str(answer))
            return answer
        return llm.chat(messages)
