# -*- coding: utf-8 -*-
"""LLM 调度：流式优先，失败降级非流式"""
class LLMDispatcher:
    def __init__(self, trunk):
        self.trunk = trunk

    def dispatch(self, messages: list, on_token=None, cancel_token=None) -> str:
        llm = self.trunk.modules.get("llm")
        if not llm:
            return "LLM未初始化"
        if on_token and hasattr(llm, "stream_chat"):
            answer = llm.stream_chat(messages, on_token=on_token,
                                     cancel_token=cancel_token)
            # 用户已按 Esc：保留已生成的部分，不要因为"答案为空"再打一次模型
            if cancel_token is not None and cancel_token.is_cancelled():
                return answer or ""
            if not answer or str(answer).startswith(("（模型错误", "本地模型错误")):
                answer = llm.chat(messages)
                if on_token and answer:
                    on_token(str(answer))
            return answer
        return llm.chat(messages)
