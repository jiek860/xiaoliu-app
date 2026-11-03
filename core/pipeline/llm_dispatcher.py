# -*- coding: utf-8 -*-
"""LLM 调度：流式优先，失败降级非流式"""
class LLMDispatcher:
    def __init__(self, trunk):
        self.trunk = trunk

    @staticmethod
    def _fallback_chat(llm, messages):
        """非流式兜底：告诉客户端"提示词已经拼好了"，别再注入小6人格。

        为什么（2026-11-01 查出来的）：本地 `LLMClient._try_local` 在
        ``inject_persona=True`` 时会 **删掉调用方所有 system 消息**，只留一句
        "你是小6，住在用户电脑里的AI朋友。" + 拟人提示。流式失败降到非流式时，
        管线辛苦拼好的人格卡 / 上下文 / 说话要求（TONE_HINT）会整段丢失，
        用户看到的是"没有上下文、也没按要求说人话"的回复。
        老接口（测试桩）只收 messages，TypeError 就按原样调。
        """
        try:
            return llm.chat(messages, inject_persona=False)
        except TypeError:
            return llm.chat(messages)

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
                answer = self._fallback_chat(llm, messages)
                if on_token and answer:
                    on_token(str(answer))
            return answer
        return self._fallback_chat(llm, messages)
