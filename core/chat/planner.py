# -*- coding: utf-8 -*-
"""回应规划器 ResponsePlanner（批次 42.2）。

输出「说话前的小纸条」：act / length / tone / must_include / avoid /
question_back，交给提示词最后一段做**强约束**，而不是继续堆人格字数。

默认 ``聊天.规划器 = shadow``：只规划、只记录，不注入提示词。
``rule`` / ``model`` 才把 plan 注入；``model`` 失败或格式不对立刻回落规则版。
"""
import json
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

_ACTS = ("ack", "answer", "answer_with_action", "comfort", "clarify", "refuse",
         "tease", "remind")
_DANGER = ("炸弹", "制毒", "盗号", "破解密码", "黑进", "入侵", "木马", "洗钱",
           "骗保", "偷税")
_COMMON_AVOID = ("作为AI", "希望对你有所帮助", "复述用户问题")
_TONES = {
    "ack": "轻松、不展开",
    "answer": "轻松但认真",
    "answer_with_action": "干脆、先结论",
    "comfort": "温和、先共情",
    "clarify": "直接、只问一个",
    "refuse": "简短坚定、给替代",
    "tease": "俏皮、不油腻",
    "remind": "轻松提醒、不啰嗦",
}
_LENGTHS = {"ack": "one", "comfort": "brief", "clarify": "one", "refuse": "brief",
            "tease": "one", "remind": "one", "answer": "brief"}
_SENTENCES = {"one": 1, "brief": 2, "open": 4}
_CHARS = {"ack": 60, "tease": 80, "clarify": 80, "remind": 70, "comfort": 100,
          "refuse": 120, "answer": 220, "answer_with_action": 220}


def _blank_plan(source="rule"):
    return {"act": "answer", "length": "brief", "tone": _TONES["answer"],
            "must_include": ["先给结论"], "avoid": list(_COMMON_AVOID),
            "question_back": False, "max_sentences": 2, "max_chars": 220,
            "source": source}


def _norm(text):
    return re.sub(r"\s+", "", str(text or ""))


def _plan(act, length=None, *, must=None, avoid=None, question_back=False,
          max_chars=None, source="rule"):
    length = length or _LENGTHS.get(act, "brief")
    return {
        "act": act, "length": length, "tone": _TONES.get(act, _TONES["answer"]),
        "must_include": list(must or []), "avoid": list(_COMMON_AVOID) + list(avoid or []),
        "question_back": bool(question_back), "max_sentences": _SENTENCES.get(length, 2),
        "max_chars": int(max_chars or _CHARS.get(act, 220)), "source": source,
    }


def render_hint(plan):
    """把 plan 变成提示词最后一段的中文强约束。"""
    if not isinstance(plan, dict) or not plan:
        return ""
    label = {"one": "1 句", "brief": "1–2 句", "open": "可展开但不超过 4 句"}
    parts = [
        "动作：%s" % plan.get("act", "answer"),
        "长度：%s（最多 %s 字）" % (label.get(plan.get("length"), "1–2 句"),
                                plan.get("max_chars", 220)),
        "语气：%s" % plan.get("tone", "轻松但认真"),
    ]
    if plan.get("must_include"):
        parts.append("必须做到：" + "；".join(plan["must_include"][:3]))
    if plan.get("avoid"):
        parts.append("不要：" + "；".join(plan["avoid"][:5]))
    parts.append("最多反问 1 个问题" if plan.get("question_back") else "不要反问")
    return "；".join(parts) + "。"


class ResponsePlanner:
    def __init__(self, trunk=None):
        self.trunk = trunk

    def plan(self, state, user_text, *, mode="rule", recent=None):
        """返回 plan；任何异常都回落到默认 plan，绝不阻断回复。"""
        try:
            state = state if isinstance(state, dict) else {}
            text = str(user_text or "")
            # 安全优先：危险请求不交给模型规划，规则直接拒绝。
            if any(w in text for w in _DANGER):
                return self._rule_plan(state, text, recent)
            if str(mode).strip().lower() == "model":
                model = self._model_plan(state, text)
                if model:
                    return model
            return self._rule_plan(state, text, recent)
        except Exception as e:
            _x6_swallowed(__name__, e, "planner")
            return _blank_plan()

    # ---------- 规则版 ----------
    def _rule_plan(self, state, text, recent):
        intent = str(state.get("intent") or "chat")
        expects = str(state.get("expects") or "")
        stripped = text.strip()
        n = len(stripped)
        brevity = str(state.get("brevity") or "")
        if brevity not in ("short", "normal", "long"):
            brevity = "short" if n <= 8 else ("normal" if n <= 40 else "long")

        if any(w in text for w in _DANGER):
            return _plan("refuse", "brief", must=["简短拒绝", "给一个替代方向"],
                         avoid=["说教", "讲大道理"])
        if intent == "correct":
            return _plan("clarify", "one", must=["先认错并确认改哪"],
                         avoid=["解释原因", "连续道歉"])
        if intent == "vent":
            return _plan("comfort", "brief", must=["先共情，再说别的"],
                         avoid=["说教", "立刻给方案", "列点"], question_back=False)
        if intent == "play":
            return _plan("tease", "one", must=["接住玩笑"], avoid=["冷笑话解释"])
        if intent == "smalltalk":
            return _plan("ack", "one", must=["回应对方"], avoid=["展开成长篇"])
        if self._repeated(recent):
            return _plan("remind", "one", must=["提一句这个聊过了"],
                         avoid=["重复上一轮原话"])
        if intent == "request_help" and n <= 4:
            return _plan("clarify", "one", must=["说明还缺哪个关键信息"],
                         avoid=["一次问多个问题"], question_back=True)
        if intent == "request_help":
            length = "open" if (brevity == "long" or n > 40) else "brief"
            return _plan("answer_with_action", length, must=["先给结论", "再给一步操作"],
                         avoid=["列 5 条", "长篇背景"])
        if intent == "ask_fact" or expects == "explanation":
            return _plan("answer", "brief" if brevity != "long" else "open",
                         must=["先回答问题"], avoid=["列 5 条", "先讲背景"])
        if brevity == "short":
            return _plan("ack", "one", must=["用一句话接住"])
        return _plan("answer", "brief", must=["先给结论"])

    def _repeated(self, recent):
        try:
            rows = [_norm(t) for t in (recent or []) if _norm(t)]
            return len(rows) >= 3 and len(set(rows[-3:])) == 1
        except Exception:
            return False

    # ---------- 模型版（可选） ----------
    def _model_plan(self, state, text):
        try:
            llm = getattr(self.trunk, "modules", {}).get("llm") if self.trunk else None
            if llm is None and self.trunk is not None:
                llm = self.trunk._load_lazy("llm")
            if llm is None or not hasattr(llm, "chat"):
                return None
            prompt = ("请为这条用户消息规划回复，只输出 JSON："
                      '{"act":"ack|answer|answer_with_action|comfort|clarify|refuse|tease|remind",'
                      '"length":"one|brief|open","tone":"...","must_include":["..."],'
                      '"avoid":["..."],"question_back":true|false,"max_chars":整数}')
            raw = llm.chat([
                {"role": "system", "content": "你是回复规划器，只输出 JSON，不解释。"},
                {"role": "user", "content": "状态:%s\n用户:%s" % (
                    json.dumps(state, ensure_ascii=False)[:500], text[:300])},
            ])
            return self._parse_model(raw)
        except Exception as e:
            _x6_swallowed(__name__, e, "planner_model")
            return None

    def _parse_model(self, raw):
        text = str(raw or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (ValueError, TypeError):
            return None
        act = str(data.get("act") or "").lower()
        if act not in _ACTS:
            return None
        length = str(data.get("length") or "").lower()
        if length not in _SENTENCES:
            length = _LENGTHS.get(act, "brief")
        try:
            max_chars = int(data.get("max_chars") or _CHARS.get(act, 220))
        except (TypeError, ValueError):
            max_chars = _CHARS.get(act, 220)
        must = [str(x)[:40] for x in (data.get("must_include") or []) if str(x).strip()][:3]
        avoid = [str(x)[:40] for x in (data.get("avoid") or []) if str(x).strip()][:5]
        plan = _plan(act, length, must=must, avoid=avoid,
                     question_back=bool(data.get("question_back")),
                     max_chars=max(20, min(600, max_chars)), source="model")
        tone = str(data.get("tone") or "").strip()
        if tone:
            plan["tone"] = tone[:30]
        return plan
