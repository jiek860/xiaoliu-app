# -*- coding: utf-8 -*-
"""回复管线编排器：把 _reply_inner 的 300 行变成 30 行的流程"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

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
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def run(self, user_input: str, on_token=None, cancel_token=None) -> str:
        t = self.trunk
        _t_start = time.time()
        try:
            if "agent_flow" not in t.modules:
                t.call("agent_flow", "__no__")
            af = t.modules.get("agent_flow")
            if af is not None and hasattr(af, "clear"):
                af.clear()          # 每轮重新记，别把上一轮的混进来
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        t._set_status("正在理解你的问题...")
        t._reply_n = getattr(t, "_reply_n", 0) + 1
        self._record("接收消息", "ok", user_input[:60])
        state_summary = self._track_state(user_input)

        # 电脑控制快速通道
        fast = self._try_computer_control(user_input)
        if fast is not None:
            self._record("电脑控制", "ok", "快速通道命中")
            self._shadow(user_input, True, _t_start, None, fast,
                         fast="computer", state=state_summary)
            return fast

        is_simple = self.ctx.is_simple(user_input)
        _t_ctx = time.time()
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
        answer = self.ld.dispatch(messages, on_token=on_token,
                                  cancel_token=cancel_token)
        self._record("模型生成", "ok" if answer else "fail",
                     "%.1f秒" % (time.time() - _t0))

        # 用户已按 Esc：跳过记忆写入、群聊合并、代码沙盒验证等收尾工作，
        # 否则"停止"之后还要再等十几秒后台动作才真正结束。
        if cancel_token is not None and cancel_token.is_cancelled():
            self._record("用户取消", "cancelled")
            self._shadow(user_input, is_simple, _t_start, _t_ctx, answer,
                         cancelled=True, state=state_summary)
            self._finish_chat(t)
            return answer or ""

        t.mem_add(user_input, answer)
        answer = self.pp.merge_group(user_input, answer, prefetch=role_fut)
        answer = self.pp.verify_code(user_input, answer)
        self.pp.kick_off_background(user_input, answer)
        self._shadow(user_input, is_simple, _t_start, _t_ctx, answer,
                     state=state_summary)
        self._record("收尾", "ok")

        self._finish_chat(t)
        return answer

    def _state_mode(self):
        """对话状态开关：off / shadow / on（批次 42.1，默认 shadow）。"""
        try:
            value = str(self.trunk.rule("聊天.状态层", "shadow") or "shadow")
        except Exception as e:
            _x6_swallowed(__name__, e, "state_mode")
            value = "shadow"
        value = value.strip().lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _track_state(self, user_input):
        """更新并落盘对话状态，返回摘要；任何失败都返回 {}。

        shadow 模式下只记录、不参与提示词拼装，用户可见行为与旧版一致；
        ``on`` 的消费方是 42.2 回应规划器，本批尚未接入。
        """
        try:
            if self._state_mode() == "off":
                return {}
            from core.chat.state import DialogueState
            base = getattr(self.trunk, "base", ".") or "."
            state = DialogueState.load(base)
            summary = state.update(user_input)
            state.save()
            return summary
        except Exception as e:
            _x6_swallowed(__name__, e, "track_state")
            return {}

    def _shadow(self, user_input, is_simple, t_start, t_ctx, answer, **extra):
        """影子状态：只记录，失败静默（批次 41.4）。"""
        try:
            now = time.time()
            payload = {
                "text": str(user_input or "")[:80],
                "chars": len(str(user_input or "")),
                "is_simple": bool(is_simple),
                "intent": self.ctx.guess_intent(user_input),
                "topic": self.ctx.guess_topic(user_input),
                "total_ms": int((now - t_start) * 1000),
                "ctx_ms": int((t_ctx - t_start) * 1000) if t_ctx else 0,
                "gen_ms": int((now - t_ctx) * 1000) if t_ctx else 0,
                "answer_chars": len(str(answer or "")),
            }
            payload.update(extra)
            self.ctx.record_shadow(payload)
        except Exception as e:
            _x6_swallowed(__name__, e, "shadow")

    def _finish_chat(self, t):
        t._chat_in_progress = False
        # 窗口长度统一由 Trunk._CHAT_ACTIVE_SEC 决定（原来这里写死 120，
        # 跟 trunk.reply() 的 25 不一致 —— 虽然那个 finally 会覆盖它，
        # 但两处常量各写各的就是下一个"改一个忘另一个"）
        t._chat_active_until = time.time() + getattr(t, "_CHAT_ACTIVE_SEC", 25)

    def _try_computer_control(self, user_input: str):
        try:
            if getattr(self.trunk, "_remote_tool_locked", False):
                allow = False
                try:
                    allow = bool(getattr(self.trunk, "_remote_tools_allowed", False)
                                 or (getattr(self.trunk, "config", {}) or {})
                                 .get("bot_allow_tools", False))
                except Exception:
                    allow = False
                if not allow:
                    return None
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
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
            self.trunk.mem_add(user_input, str(result)[:200])
            return str(result)
        except Exception as e:
            self.trunk._log(f"电脑控制失败: {e}")
            return None
