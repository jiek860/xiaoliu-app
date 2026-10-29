# -*- coding: utf-8 -*-
"""生成后校验器 ResponseCritic（批次 42.3）。

只做规则检查与轻量修复，不重跑检索：
    超长 / 复述用户 / 重复句 / 禁语 / 列点 / emoji 超预算 / 多余反问 / 疑似答非所问。

返回 ``{ok, issues, fixed_text, metrics, source}``；任何异常都返回原文。
``chat.critic`` 开关默认 ``shadow``：只记录 issues，不改回复；``on`` 才替换文本。
``chat.critic_rewrite`` 打开且模型可用时，允许一次轻量重写（失败即保留规则修复）。
"""
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

        for word, repl in _BANNED:
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
