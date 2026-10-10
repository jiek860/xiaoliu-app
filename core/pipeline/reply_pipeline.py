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

    def _record(self, name, status, detail=""):
        """把这一步记到 agent_flow

        agent_flow 这个模块登记了很久没人调用 —— 它做的就是"记录执行步骤供可视化"。
        模块内部只留最近 50 条、纯内存，任何异常都不影响回复。
        """
        try:
            t = self.trunk
            if "agent_flow" not in t.modules:
                t.call("agent_flow", "__no__")
            af = t.modules.get("agent_flow")
            if af is not None and hasattr(af, "record_step"):
                af.record_step(name, status, detail)
        except Exception:
            pass

    def run(self, user_input: str, on_token=None) -> str:
        t = self.trunk
        try:
            if "agent_flow" not in t.modules:
                t.call("agent_flow", "__no__")
            af = t.modules.get("agent_flow")
            if af is not None and hasattr(af, "clear"):
                af.clear()          # 每轮重新记，别把上一轮的混进来
        except Exception:
            pass
        t._set_status("正在理解你的问题...")
        t.publish("perceive", user_input)
        t.last_chat = time.time()
        t._reply_n = getattr(t, "_reply_n", 0) + 1
        self._record("接收消息", "ok", user_input[:60])

        # 电脑控制快速通道
        fast = self._try_computer_control(user_input)
        if fast is not None:
            self._record("电脑控制", "ok", "快速通道命中")
            return fast

        is_simple = self.ctx.is_simple(user_input)
        context = self.ctx.build(user_input, is_simple)
        self._record("组装上下文", "ok", "简单=%s" % is_simple)

        t._set_status("正在思考...")
        messages = self.pa.assemble(user_input, context, is_simple)
        self._record("拼提示词", "ok")

        # 先把群聊角色回复发出去，让它和主回复的生成**并行**。
        # 原来角色回复是等主回复生成完再串着跑的（生成 12 秒 → 再等角色 11 秒），
        # 一轮多花十几秒。而走真实子智能体的那几个角色并不依赖主回复。
        role_fut = None
        try:
            gc = t._load_lazy("group_chat")
            if gc is not None and hasattr(gc, "start_roles"):
                role_fut = gc.start_roles(user_input)
        except Exception:
            role_fut = None

        _t0 = time.time()
        answer = self.ld.dispatch(messages, on_token=on_token)
        self._record("模型生成", "ok" if answer else "fail",
                     "%.1f秒" % (time.time() - _t0))

        t.mem_add(user_input, answer)
        answer = self.pp.merge_group(user_input, answer, prefetch=role_fut)
        answer = self.pp.verify_code(user_input, answer)
        self.pp.kick_off_background(user_input, answer)
        self._record("收尾", "ok")

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
