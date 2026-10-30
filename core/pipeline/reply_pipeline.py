# -*- coding: utf-8 -*-
"""回复管线编排器：把 _reply_inner 的 300 行变成 30 行的流程"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import time
import zlib
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
        gray = self._gray_on(state_summary)
        planner_mode = self._planner_mode()
        if gray and planner_mode == "shadow":
            planner_mode = "rule"
        plan = self._plan(user_input, state_summary, planner_mode)
        _t_ctx = time.time()
        context = self.ctx.build(user_input, is_simple)
        self._record("组装上下文", "ok", "简单=%s" % is_simple)

        t._set_status("正在思考...")
        plan_for_prompt = plan if planner_mode in ("rule", "model") else None
        messages = self.pa.assemble(user_input, context, is_simple,
                                    plan=plan_for_prompt, state=state_summary,
                                    gray=gray)
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
                         cancelled=True, state=state_summary, plan=plan,
                         gray=gray)
            self._finish_chat(t)
            return answer or ""

        t.mem_add(user_input, answer)
        memory = self._remember(user_input)
        answer, critic = self._critique(user_input, answer, plan, gray=gray)
        answer = self.pp.merge_group(user_input, answer, prefetch=role_fut)
        answer = self.pp.verify_code(user_input, answer)
        self.pp.kick_off_background(user_input, answer)
        self._shadow(user_input, is_simple, _t_start, _t_ctx, answer,
                     state=state_summary, plan=plan, critic=critic,
                     persona=getattr(self.pa, "last_persona", {}), gray=gray,
                     memory=memory)
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

    def _gray_on(self, state_summary):
        """灰度：按会话 id 稳定分流，0=全关，100=全开（批次 42.5）。"""
        try:
            pct = int(self.trunk.rule("聊天.灰度比例", 0) or 0)
        except (TypeError, ValueError):
            pct = 0
        if pct <= 0:
            return False
        if pct >= 100:
            return True
        session = str((state_summary or {}).get("session") or "")
        if not session:
            return False
        return (zlib.crc32(session.encode("utf-8")) % 100) < pct

    def _planner_mode(self):
        """规划器开关：off / shadow / rule / model（批次 42.2，默认 shadow）。"""
        try:
            value = str(self.trunk.rule("聊天.规划器", "shadow") or "shadow")
        except Exception as e:
            _x6_swallowed(__name__, e, "planner_mode")
            value = "shadow"
        value = value.strip().lower()
        return value if value in ("off", "shadow", "rule", "model") else "shadow"

    def _plan(self, user_input, state_summary, mode):
        """生成回应计划；shadow 只记录，rule/model 才注入提示词。"""
        if mode == "off":
            return {}
        try:
            from core.chat.planner import ResponsePlanner
            planner = ResponsePlanner(self.trunk)
            plan = planner.plan(state_summary, user_input,
                                mode="model" if mode == "model" else "rule",
                                recent=self._recent_user_texts())
            if isinstance(plan, dict) and plan:
                plan.setdefault("emoji_budget", self._emoji_budget(user_input))
            return plan
        except Exception as e:
            _x6_swallowed(__name__, e, "plan")
            return {}

    _EMOJI_WORK_WORDS = ("重构", "修复", "报错", "写个", "写一个", "实现",
                          "改代码", "修改代码", "加个函数", "函数")

    def _emoji_budget(self, user_input=""):
        """人格卡风格决定的 emoji 预算；工作态（代码任务）为 0，关闭或异常时用 2。"""
        try:
            low = str(user_input or "").lower()
            if any(w in low for w in self._EMOJI_WORK_WORDS):
                return 0
            if self.trunk.rule("聊天.人格卡", "on") == "off":
                return 2
            from core.chat.persona_card import PersonaCard
            card = PersonaCard.load(getattr(self.trunk, "base", ".") or ".")
            return card.emoji_budget(self.trunk.rule("聊天.人格风格", ""))
        except Exception as e:
            _x6_swallowed(__name__, e, "emoji_budget")
            return 2

    def _recent_user_texts(self):
        try:
            rows = self.trunk.mem_recent(6) or []
            return [str(r.get("u") or r.get("text") or "")
                    for r in rows if isinstance(r, dict)]
        except Exception as e:
            _x6_swallowed(__name__, e, "recent_texts")
            return []

    def _critic_mode(self):
        """校验器开关：off / shadow / on（批次 42.3，默认 shadow）。"""
        try:
            value = str(self.trunk.rule("聊天.校验器", "shadow") or "shadow")
        except Exception as e:
            _x6_swallowed(__name__, e, "critic_mode")
            value = "shadow"
        value = value.strip().lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _critique(self, user_input, answer, plan, gray=False):
        """返回 (最终文本, 校验摘要)；shadow 只记录，on/灰度 才替换。"""
        mode = self._critic_mode()
        if gray and mode == "shadow":
            mode = "on"
        if mode == "off":
            return answer, {}
        try:
            from core.chat.critic import ResponseCritic
            result = ResponseCritic(self.trunk).check(
                answer, plan, user_text=user_input)
            fixed = result.get("fixed_text") or answer
            summary = {
                "ok": bool(result.get("ok")),
                "issues": list(result.get("issues") or [])[:8],
                "source": result.get("source", "rule"),
                "before": len(str(answer or "")),
                "after": len(str(fixed or "")),
            }
            return (fixed if mode == "on" else answer), summary
        except Exception as e:
            _x6_swallowed(__name__, e, "critique")
            return answer, {}

    def _remember(self, user_input):
        """记忆写入：强信号立即写，普通对话每 5 轮写摘要（批次 43.2）。

        shadow 只记录会写什么、不落盘；on 才真正追加。异常静默，不阻断回复。
        """
        mode = self.ctx.memory_mode()
        if mode == "off":
            return {}
        try:
            from core.chat.memory_v2 import MemoryV2
            base = getattr(self.trunk, "base", ".") or "."
            store = MemoryV2(base)
            rounds = int(getattr(self.trunk, "_reply_n", 0) or 0)
            result = store.remember(
                user_input, rounds=rounds, recent=self._recent_user_texts(),
                dry_run=(mode == "shadow"))
            cards = result.get("cards") or []
            summary = {"reason": result.get("reason", ""),
                       "count": len(cards),
                       "written": int(result.get("written") or 0)}
            if mode == "shadow" and cards:
                self.ctx.record_shadow({
                    "kind": "memory_write",
                    "reason": summary["reason"],
                    "count": summary["count"],
                    "preview": [str(c.get("text") or "")[:60]
                                for c in cards[:3]],
                })
            return summary
        except Exception as e:
            _x6_swallowed(__name__, e, "memory_write")
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
