# -*- coding: utf-8 -*-
"""回复管线编排器：把 _reply_inner 的 300 行变成 30 行的流程"""
import time
from core.pipeline.context_builder import ContextBuilder
from core.pipeline.prompt_assembler import PromptAssembler
from core.pipeline.llm_dispatcher import LLMDispatcher
from core.pipeline.post_processor import PostProcessor


class ReplyPipeline:
    def __init__(self, trunk):
        self.trunk = trunk
        self.ctx = ContextBuilder(trunk)
        self.pa = PromptAssembler(trunk)
        self.ld = LLMDispatcher(trunk)
        self.pp = PostProcessor(trunk)

    def run(self, user_input: str, on_token=None) -> str:
        t = self.trunk
        t._set_status("正在理解你的问题...")
        t.publish("perceive", user_input)
        t.last_chat = time.time()
        t._reply_n = getattr(t, "_reply_n", 0) + 1

        # 电脑控制快速通道
        fast = self._try_computer_control(user_input)
        if fast is not None:
            return fast

        is_simple = self.ctx.is_simple(user_input)
        context = self.ctx.build(user_input, is_simple)

        t._set_status("正在思考...")
        messages = self.pa.assemble(user_input, context, is_simple)

        answer = self.ld.dispatch(messages, on_token=on_token)

        t.mem_add(user_input, answer)
        answer = self.pp.merge_group(user_input, answer)
        answer = self.pp.verify_code(user_input, answer)
        self.pp.kick_off_background(user_input, answer)

        t._chat_in_progress = False
        t._chat_active_until = time.time() + 120
        return answer

    def _try_computer_control(self, user_input: str):
        try:
            cc = self.trunk._load_lazy("computer_controller")
            if not cc:
                return None
            handled, result = cc.try_handle(user_input)
            if not handled:
                return None
            self.trunk._log(f"电脑控制: {user_input[:40]} -> {str(result)[:60]}")
            llm = self.trunk.modules.get("llm")
            if llm:
                try:
                    summary = llm.chat([
                        {"role": "system", "content":
                         "你是小6，操作已经执行完毕。用一句简短中文告诉用户结果，不要编造。"},
                        {"role": "user", "content":
                         f"用户说: {user_input[:120]}\n执行结果: {str(result)[:300]}"},
                    ])
                    if summary and not summary.startswith("本地模型错误"):
                        result = summary
                except Exception:
                    pass
            self.trunk.mem_add(user_input, str(result)[:200])
            return str(result)
        except Exception as e:
            self.trunk._log(f"电脑控制失败: {e}")
            return None
