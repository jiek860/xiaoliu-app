# -*- coding: utf-8 -*-
"""评测用的纯函数指标。

只依赖标准库：不调模型、不碰 Qt、不读网络，方便单元测试和 CI。
聊天/代码质量评测共用这些口径，避免每处各写一套。
"""
from __future__ import annotations

import re

# 句末标点：中文句号/感叹号/问号/分号，以及英文句点（后面是空白或结尾）
_SENT_END = re.compile(r"[。！？!?；;]|\.(?=\s|$)")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_SPACE = re.compile(r"\s+")


def normalize(text):
    """去掉首尾空白，把连续空白压成一个空格。"""
    return _SPACE.sub(" ", str(text or "")).strip()


def sentences(text):
    """按中英文句末标点切句，过滤空句。"""
    raw = _SENT_END.split(normalize(text))
    return [s.strip() for s in raw if s and s.strip()]


def sentence_count(text):
    return len(sentences(text))


def char_count(text):
    return len(normalize(text).replace(" ", ""))


def emoji_count(text):
    return len(_EMOJI.findall(str(text or "")))


def question_count(text):
    return str(text or "").count("?") + str(text or "").count("？")


def banned_hits(text, banned):
    """命中禁语表，返回命中的词列表（保持表内顺序）。"""
    low = str(text or "").lower()
    return [w for w in (banned or []) if w and w.lower() in low]


def missing_any(text, any_of):
    """要求至少出现一个词；表为空时视为满足。"""
    if not any_of:
        return []
    low = str(text or "").lower()
    if any(w.lower() in low for w in any_of):
        return []
    return list(any_of)


def ngram_repeat_rate(texts, n=8):
    """一组文本的 n-gram 重复率（重复次数 / 总次数）。

    中文按字符、英文按字符都适用；空白与常见标点先移除。
    重复率高说明车轱辘话多。
    """
    n = max(2, int(n or 8))
    grams = []
    for text in texts or []:
        clean = re.sub(r"[\s，。！？!?；;：:、,.]+", "", str(text or ""))
        if len(clean) < n:
            continue
        grams.extend(clean[i:i + n] for i in range(0, len(clean) - n + 1))
    if not grams:
        return 0.0
    repeated = len(grams) - len(set(grams))
    return round(repeated / float(len(grams)), 4)


def eval_chat(text, expect):
    """按期望检查一条回复。

    expect 支持：
        max_sentences / max_chars / max_questions / max_emoji
        must_not（禁语）/ must_include_any（至少出现一个）
    返回 {ok, issues, metrics}。
    """
    expect = dict(expect or {})
    issues = []
    text = str(text or "")
    metrics = {
        "chars": char_count(text),
        "sentences": sentence_count(text),
        "questions": question_count(text),
        "emoji": emoji_count(text),
    }
    if "max_sentences" in expect and metrics["sentences"] > expect["max_sentences"]:
        issues.append("句子过多：%d > %d"
                      % (metrics["sentences"], expect["max_sentences"]))
    if "max_chars" in expect and metrics["chars"] > expect["max_chars"]:
        issues.append("字数过多：%d > %d"
                      % (metrics["chars"], expect["max_chars"]))
    if "max_questions" in expect and metrics["questions"] > expect["max_questions"]:
        issues.append("问号过多：%d > %d"
                      % (metrics["questions"], expect["max_questions"]))
    if "max_emoji" in expect and metrics["emoji"] > expect["max_emoji"]:
        issues.append("表情过多：%d > %d"
                      % (metrics["emoji"], expect["max_emoji"]))
    hits = banned_hits(text, expect.get("must_not"))
    if hits:
        issues.append("命中禁语：%s" % "、".join(hits))
    missed = missing_any(text, expect.get("must_include_any"))
    if missed:
        issues.append("缺少要点：%s" % "、".join(missed))
    return {"ok": not issues, "issues": issues, "metrics": metrics}
