# -*- coding: utf-8 -*-
"""Prompt 组装：人格 + 反思建议 + few-shot + 历史"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

class PromptAssembler:
    def __init__(self, trunk):
        self.trunk = trunk
        self.last_persona = {}

    def assemble(self, user_input: str, context: str, is_simple: bool,
                 plan=None, state=None, gray=False) -> list:
        pers_hint, few_shot = self._persona(user_input, is_simple)
        few_shot = self._with_examples(few_shot, plan, state, gray)
        persona = self._compose_persona(pers_hint, plan, state, gray)

        messages = [{"role": "system", "content": persona}]
        skill_prompt = str(getattr(self.trunk, "_active_skill_prompt", "") or "")
        if skill_prompt:
            messages.append({"role": "system",
                             "content": skill_prompt[:2000]})
        if context:
            messages.append({"role": "system", "content": "相关知识: " + context})

        adv = self._reflect_advice(is_simple)
        if adv:
            messages.append({"role": "system", "content": "自我反思建议: " + adv})

        for ex in few_shot:
            messages.append({"role": "user", "content": ex["u"]})
            messages.append({"role": "assistant", "content": ex["a"]})

        hist = self._history(is_simple)
        for h in hist:
            messages.append({"role": "user", "content": h["u"]})
            messages.append({"role": "assistant", "content": h["a"]})

        # 批次 42.2：规划结果放在最后一段做硬约束（越靠后模型越服从）。
        hint = self._plan_hint(plan)
        if hint:
            messages.append({"role": "system",
                             "content": "本轮回复要求（必须遵守）：" + hint})

        messages.append({"role": "user", "content": user_input})
        return messages

    def _plan_hint(self, plan):
        if not plan:
            return ""
        try:
            from core.chat.planner import render_hint
            return render_hint(plan)
        except Exception as e:
            _x6_swallowed(__name__, e, "plan_hint")
            return ""

    def _persona(self, user_input, is_simple):
        pers_hint, few_shot = "", []
        if is_simple:
            return pers_hint, few_shot
        try:
            self.trunk._load_lazy("personality")
            pers = self.trunk.modules.get("personality")
            if pers:
                pers_hint = pers.full_hint(user_input)
                few_shot = pers.few_shot_examples()
        except Exception as e:
            self.trunk._log(f"人格引擎失败: {e}")
        return pers_hint, few_shot

    def _compose_persona(self, pers_hint: str, plan=None, state=None,
                         gray=False) -> str:
        config = getattr(self.trunk, "config", {}) or {}
        custom = str(config.get("ai_persona", "") or "").strip()
        mode = self._card_mode()
        if gray and mode == "shadow":
            mode = "on"
        self.last_persona = {"mode": mode, "gray": bool(gray)}
        if mode != "off":
            try:
                from core.chat.persona_card import PersonaCard
                style = self.trunk.rule("聊天.人格风格", "")
                base = getattr(self.trunk, "base", ".") or "."
                card = PersonaCard.load(base)
                built = card.build(style=style, state=state, plan=plan)
                self.last_persona.update({
                    "style": built["style"], "version": built["version"],
                    "chars": built["chars"], "layers": built["layers"],
                })
                if mode == "on" and not custom:
                    return built["text"] + (
                        "\n" + pers_hint[:280] if pers_hint else "")
            except Exception as e:
                _x6_swallowed(__name__, e, "persona_card")
        if custom:
            return custom + ("\n\n" + pers_hint if pers_hint else "")
        return pers_hint if pers_hint else "你是小6，住在用户电脑里的AI朋友。"

    def _with_examples(self, few_shot, plan, state, gray=False):
        """批次 42.5：人格卡/规划器/灰度启用时，按 topic + act 补 2 组短示例。"""
        rows = list(few_shot or [])
        try:
            if not gray and plan is None and self._card_mode() != "on":
                return rows
            from core.chat.fewshot import pick
            base = getattr(self.trunk, "base", ".") or "."
            topic = (state or {}).get("topic", "")
            act = (plan or {}).get("act", "")
            known = {str(r.get("u")) for r in rows}
            extra = [r for r in pick(base, topic, act, 2) if r["u"] not in known]
            return rows + extra[:2]
        except Exception as e:
            _x6_swallowed(__name__, e, "fewshot")
            return rows

    def _card_mode(self):
        """人格卡开关：off / shadow / on（批次 42.4，默认 shadow）。"""
        try:
            value = str(self.trunk.rule("聊天.人格卡", "shadow") or "shadow")
        except Exception as e:
            _x6_swallowed(__name__, e, "card_mode")
            value = "shadow"
        value = value.strip().lower()
        return value if value in ("off", "shadow", "on") else "shadow"

    def _reflect_advice(self, is_simple: bool) -> str:
        if is_simple:
            return ""
        try:
            refl = self.trunk.modules.get("self_reflect")
            if not refl:
                self.trunk._load_lazy("self_reflect")
                refl = self.trunk.modules.get("self_reflect")
            if refl and hasattr(refl, "get_advice"):
                return refl.get_advice() or ""
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return ""

    def _history(self, is_simple: bool):
        n = 3 if is_simple else 15
        return self.trunk.mem_recent(n)
