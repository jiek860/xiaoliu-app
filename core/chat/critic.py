# -*- coding: utf-8 -*-
"""生成后校验器 ResponseCritic（批次 42.3）+ 多维反思规则（批次 48.1）。

只做规则检查与轻量修复，不重跑检索：
    超长 / 复述用户 / 重复句 / 禁语 / 列点 / emoji 超预算 / 多余反问 / 疑似答非所问。

返回 ``{ok, issues, fixed_text, metrics, source}``；任何异常都返回原文。
``chat.critic`` 开关默认 ``shadow``：只记录 issues，不改回复；``on`` 才替换文本。
``chat.critic_rewrite`` 打开且模型可用时，允许一次轻量重写（失败即保留规则修复）。

48.1 起本文件还提供 ``rubric_dims`` 等纯函数：按准确/贴合/人格/有用/长度
五个维度给回答打 1-5 分。它们不调模型，「失败库/建议晋升」的存储放在
``core.chat.fewshot``，避免本文件超过 600 行。
"""
import json
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_SENT = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_BULLET = re.compile(r"(^|\n)\s*(?:[-*•]|\d+[.、])\s*")
_COMMON_AVOID = ("作为AI", "希望对你有所帮助", "复述用户问题")
_BANNED = (
    ("作为AI，", ""), ("作为AI", "我"), ("我无法", "我不太能"),
    ("希望对你有所帮助", ""), ("需要注意的是", ""), ("总之，", ""),
    ("请问还有什么可以帮您", ""), ("如果您需要", "需要的话"),
    ("你应该", "你可以"), ("你必须", "你得"), ("别难过", "我在"),
    ("这取决于很多因素", ""), ("因人而异", ""),
)
_DEFAULT_EMOJI_BUDGET = 2


def _sentences(text):
    return [m.group(0).strip() for m in _SENT.finditer(text) if m.group(0).strip()]


def _metric(text):
    return {"chars": len(text), "sentences": len(_sentences(text)),
            "emoji": len(_EMOJI.findall(text)),
            "questions": text.count("？") + text.count("?")}


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fit_length(text, max_sentences, max_chars):
    sents = _sentences(text)
    if len(sents) > max_sentences:
        text = "".join(sents[:max_sentences])
    if len(text) <= max_chars:
        return text
    cut = text[:max(1, max_chars - 1)]
    for mark in ("。", "！", "？", "；", ".", "!", "?"):
        pos = cut.rfind(mark)
        if pos >= max_chars * 0.6:
            return cut[:pos + 1]
    return cut.rstrip("，,、 ") + "。"


def _strip_restate(text, user_text):
    q = str(user_text or "").strip().rstrip("？?。！!")
    if len(q) >= 6 and text.startswith(q):
        return re.sub(r"^[，,：:\s]+", "", text[len(q):])
    return text


def _dedupe_sentences(text):
    sents = _sentences(text)
    if len(sents) == len(set(sents)):
        return text
    out, seen = [], set()
    for sent in sents:
        if sent in seen:
            continue
        seen.add(sent)
        out.append(sent)
    return "".join(out)


def _flatten_bullets(text):
    rows = [r.strip() for r in _BULLET.split(text) if r.strip()]
    if not rows:
        return text
    joined = "，".join(rows)
    return re.sub(r"(，){2,}", "，", joined)


def _trim_emoji(text, budget):
    found = list(_EMOJI.finditer(text))
    if len(found) <= budget:
        return text
    for match in reversed(found[budget:]):
        text = text[:match.start()] + text[match.end():]
    return text


def _off_topic(user_text, answer):
    q = str(user_text or "")
    grams = {q[i:i + 2] for i in range(max(0, len(q) - 1))}
    grams = {g for g in grams if g.strip()}
    if not grams:
        return False
    return not any(g in answer for g in grams)


class ResponseCritic:
    def __init__(self, trunk=None):
        self.trunk = trunk

    def check(self, text, plan=None, *, user_text="") -> dict:
        original = str(text or "")
        try:
            return self._check(original, plan or {}, str(user_text or ""))
        except Exception as e:
            _x6_swallowed(__name__, e, "critic")
            return {"ok": True, "issues": [], "fixed_text": original,
                    "metrics": _metric(original), "source": "rule"}

    def _check(self, original, plan, user_text):
        issues = []
        if not original.strip():
            return {"ok": False, "issues": ["empty"], "fixed_text": "",
                    "metrics": _metric(""), "source": "rule"}

        max_sentences = max(1, _as_int(plan.get("max_sentences"), 4))
        max_chars = max(20, _as_int(plan.get("max_chars"), 400))
        emoji_budget = max(0, _as_int(plan.get("emoji_budget"), _DEFAULT_EMOJI_BUDGET))
        has_code = "```" in original
        text = original

        for word, repl in self._banned_pairs():
            if word in text:
                issues.append("banned")
                text = text.replace(word, repl)
        if not text.strip():
            text = original

        if _strip_restate(text, user_text) != text:
            issues.append("restate")
            text = _strip_restate(text, user_text)

        deduped = _dedupe_sentences(text)
        if deduped != text:
            issues.append("repeat")
            text = deduped

        if not has_code and _BULLET.search(text):
            issues.append("bullets")
            text = _flatten_bullets(text)

        if len(_EMOJI.findall(text)) > emoji_budget:
            issues.append("emoji")
            text = _trim_emoji(text, emoji_budget)

        questions = text.count("？") + text.count("?")
        if plan.get("question_back"):
            if questions == 0:
                issues.append("question")
                text = text.rstrip("。！! ") + "？你想先从哪一步开始？"
        elif questions > 1:
            issues.append("question")
            if not has_code:
                text = re.sub(r"[？?]", "。", text)

        if not has_code:
            fitted = _fit_length(text, max_sentences, max_chars)
            if fitted != text:
                issues.append("too_long")
                text = fitted
        elif len(text) > max_chars * 3:
            issues.append("too_long")

        if plan.get("act") in ("answer", "answer_with_action") and len(user_text) >= 8:
            if _off_topic(user_text, text):
                issues.append("off_topic")

        source = "rule"
        if issues and self._rewrite_enabled():
            rewritten = self._rewrite(original, text, plan, user_text, max_chars)
            if rewritten:
                text, source = rewritten, "model"

        metrics = _metric(text)
        ok = not [i for i in issues if i in ("empty", "too_long", "off_topic")]
        return {"ok": ok, "issues": sorted(set(issues)), "fixed_text": text,
                "metrics": metrics, "source": source}

    # ---------- 禁语（42.4 起以人格卡为准；48.2 起含晋升规则） ----------
    def _banned_pairs(self):
        rows = list(_BANNED)
        try:
            from core.chat.persona_card import PersonaCard
            base = getattr(self.trunk, "base", ".") or "."
            known = {w for w, _ in rows}
            rows += [(w, r) for w, r in PersonaCard.load(base).banned_pairs()
                     if w not in known]
        except Exception as e:
            _x6_swallowed(__name__, e, "banned_pairs")
        rows.sort(key=lambda row: -len(row[0]))
        return rows

    # ---------- 可选模型重写 ----------
    def _rewrite_enabled(self):
        try:
            return bool(self.trunk.rule("聊天.校验重写", False))
        except Exception:
            return False

    def _rewrite(self, original, text, plan, user_text, max_chars):
        try:
            llm = getattr(self.trunk, "modules", {}).get("llm")
            if llm is None:
                llm = self.trunk._load_lazy("llm")
            if llm is None or not hasattr(llm, "chat"):
                return ""
            raw = llm.chat([
                {"role": "system", "content":
                 "你在做去 AI 腔的轻量重写：保留事实，去掉禁语与重复，"
                 "不超过 %d 字，只输出改写后的正文。" % max_chars},
                {"role": "user", "content": "用户：%s\n原回复：%s\n规则修复版：%s"
                 % (user_text[:200], original[:800], text[:800])},
            ])
            out = str(raw or "").strip()
            if not out or len(out) > max_chars * 1.3:
                return ""
            return out
        except Exception as e:
            _x6_swallowed(__name__, e, "critic_rewrite")
            return ""


def render_plan_avoid(plan):
    """给提示词复用的禁语段（42.4 会接人格卡数据）。"""
    avoid = list(_COMMON_AVOID)
    if isinstance(plan, dict):
        avoid += [str(x) for x in (plan.get("avoid") or [])]
    seen = []
    for item in avoid:
        if item and item not in seen:
            seen.append(item)
    return seen


# ================================================================
# 多维反思规则（48.1）
# 纯函数：不调模型、不读写文件；存储与晋升在 core.chat.fewshot。
# ================================================================
_DIM_KEYS = ("准确", "贴合", "人格", "有用", "长度")
_DIM_ALIASES = {
    "准确": ("准确", "accuracy", "acc"),
    "贴合": ("贴合", "相关", "relevance", "relevant"),
    "人格": ("人格", "persona", "风格", "style"),
    "有用": ("有用", "useful", "helpful", "utility"),
    "长度": ("长度", "length", "len"),
}
LOW_TOTAL = 3.0
LOW_DIM = 2
FALLBACK_RULES = {
    "too_long": {"type": "avoid", "value": "回复控制在 3 句内，别铺陈",
                 "style": "说得短一点，最多三句。"},
    "restate": {"type": "avoid", "value": "不要复述用户问题，直接回答",
                "banned": ["你问的是", "你的问题是", "你想了解"]},
    "banned": {"type": "avoid", "value": "别说客服腔和“作为 AI”这类话",
               "banned": ["作为AI", "作为 AI", "很高兴为您",
                          "希望对你有所帮助", "希望对您有帮助"]},
    "bullets": {"type": "avoid", "value": "少列点，能一句话说清就别分条"},
    "off_topic": {"type": "avoid", "value": "先回答问题本身，别跑题"},
    "too_short": {"type": "avoid", "value": "回答具体一点，别只回几个字"},
    "error": {"type": "avoid", "value": "答不出来就说原因，别用错误占位蒙混"},
}
_CUSTOMER_WORDS = ("作为AI", "作为 AI", "很高兴为您", "希望对你有所帮助",
                   "希望对您有帮助", "我是一个人工智能", "以下是", "综上所述")
_RESTATE_WORDS = ("你问的是", "你的问题是", "你想了解", "关于你提到的")
_OFFTOPIC_WORDS = ("顺便说", "另外我还想", "换个话题")


def _clamp(value, lo=1, hi=5):
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return lo


def _norm(text):
    return re.sub(r"\s+", "", str(text or "")).lower()


def _bigrams(text):
    text = _norm(text)
    return {text[i:i + 2] for i in range(max(0, len(text) - 1))}


def _overlap(a, b):
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return 0.0
    return len(x & y) / float(len(x | y))


def _has_any(text, words):
    low = str(text or "").lower()
    return any(str(word).lower() in low for word in words)


def rubric_dims(user_input, ai_response):
    """规则维度：不调模型也能给出稳定底线分（1-5）。"""
    q = str(user_input or "")
    a = str(ai_response or "")
    qn, an = _norm(q), _norm(a)
    ov = _overlap(q, a)
    is_question = bool(re.search(r"[?？]|怎么|为什么|如何|吗|能不能|可以", q))
    wants_code = bool(re.search(r"代码|报错|函数|实现|脚本|命令|bug|error", q))

    accuracy = 5
    if not an or len(an) < 5:
        accuracy = 1
    elif a.startswith(("（抱歉", "本地模型错误", "（模型错误")):
        accuracy = 1
    elif is_question and len(qn) >= 8 and ov < 0.04:
        accuracy = 2
    elif _has_any(a, _OFFTOPIC_WORDS) and not _has_any(q, _OFFTOPIC_WORDS):
        accuracy = 3

    relevance = 5
    if not an:
        relevance = 1
    elif is_question and ov < 0.10:
        relevance = 2 if len(qn) >= 8 else 3
    elif _has_any(a, _RESTATE_WORDS):
        relevance = min(relevance, 3)

    persona = 5
    if _has_any(a, _CUSTOMER_WORDS):
        persona = 2
    elif _has_any(a, _RESTATE_WORDS):
        persona = 3
    if len(re.findall(r"^\s*(?:[-*]|\d+[.、])", a, re.M)) >= 4 and len(an) < 300:
        persona = min(persona, 3)

    if wants_code:
        useful = 5 if ("```" in a or re.search(r"\bdef\b|pip |npm |import ", a)) else 2
    elif re.search(r"难受|难过|烦|累|焦虑|生气|委屈|崩溃", q):
        useful = 5 if re.search(r"辛苦|理解|陪|慢慢来|抱抱|别急", a) else 3
    else:
        useful = 5 if (re.search(r"\d", a) or len(an) >= 20) else 2
    if accuracy == 1:
        useful = 1

    n = len(an)
    if wants_code:
        length = 5 if n <= 3000 else (3 if n <= 5000 else 2)
    elif n < 5:
        length = 1
    elif n < 15:
        length = 3
    elif n <= 400:
        length = 5
    elif n <= 800:
        length = 3
    else:
        length = 2
    return {"准确": _clamp(accuracy), "贴合": _clamp(relevance),
            "人格": _clamp(persona), "有用": _clamp(useful),
            "长度": _clamp(length)}


def rubric_total(dims):
    values = [float(dims.get(key) or 0) for key in _DIM_KEYS]
    return round(sum(values) / float(len(values)), 2) if values else 0.0


def rubric_issues(dims, user_input="", ai_response=""):
    out = []
    a = str(ai_response or "")
    if not a.strip() or a.startswith(("（抱歉", "本地模型错误", "（模型错误")):
        out.append("error")
    if dims.get("长度", 5) <= 2 and len(a) > 800:
        out.append("too_long")
    if len(a) < 15:
        out.append("too_short")
    if _has_any(a, _RESTATE_WORDS):
        out.append("restate")
    if _has_any(a, _CUSTOMER_WORDS):
        out.append("banned")
    if len(re.findall(r"^\s*(?:[-*]|\d+[.、])", a, re.M)) >= 4:
        out.append("bullets")
    if dims.get("贴合", 5) <= 2 or dims.get("准确", 5) <= 2:
        out.append("off_topic")
    return list(dict.fromkeys(out))


def parse_model_json(raw):
    """解析模型返回的维度 JSON；失败返回 None（不抛异常）。"""
    match = re.search(r"\{.*\}", str(raw or ""), re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    dims, suggestion = {}, ""
    for key, aliases in _DIM_ALIASES.items():
        for alias in aliases:
            if alias in data:
                dims[key] = _clamp(data.get(alias))
                break
    for key in ("建议", "suggestion", "改进"):
        if key in data:
            suggestion = str(data.get(key) or "")[:100]
            break
    return dims, suggestion
