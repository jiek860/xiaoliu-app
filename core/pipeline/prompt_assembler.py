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

    def assemble(self, user_input: str, context: str, is_simple: bool) -> list:
        pers_hint, few_shot = self._persona(user_input, is_simple)
        persona = self._compose_persona(pers_hint)

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

        messages.append({"role": "user", "content": user_input})
        return messages

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

    def _compose_persona(self, pers_hint: str) -> str:
        custom = self.trunk.config.get("ai_persona", "").strip()
        if custom:
            return custom + ("\n\n" + pers_hint if pers_hint else "")
        return pers_hint if pers_hint else "你是小6，住在用户电脑里的AI朋友。"

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
