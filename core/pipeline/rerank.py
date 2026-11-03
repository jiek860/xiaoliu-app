# -*- coding: utf-8 -*-
"""知识重排（第 4 批 A2 / 深度④）：词面 + 向量分数融合 → 去重 → MMR → 带来源段落。

为什么要它
----------
回复前会把三路知识（向量检索 / 记忆卡 / 知识图谱）拼进上下文。原来三路是
各自 ``"\n".join`` 后直接接在提示词后面，问题有三个：

1. **没有统一排序**：向量库给的是余弦分、记忆卡给的是 0.45*相关+…、知识图谱
   干脆没有分，三路混在一起时"哪条更该排前面"没人管；
2. **重复**：同一条偏好可能同时出现在向量库和记忆卡里，白占上下文预算；
3. **来源丢失**：模型看到一坨文本，说不清"这句是你上次说的还是知识库里的"。

这里做一件事：把三路收成统一的 ``[{text, source, score}]``，用 **词面重合 +
向量分** 融合打分，按分数去重（相近条目合并来源），再做 MMR 多样性挑选，
最后输出成带序号的 "相关知识：① …（来源：记忆）"。

约束：纯函数、零 IO、零模型调用；任何脏数据都当"没有这条"，绝不抛出。
"""
from __future__ import annotations

import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_TOP_K = 5
DEFAULT_LAMBDA = 0.7        # MMR：相关性权重（1-λ 给多样性）
DEFAULT_DEDUP = 0.82        # 近似重复阈值（bigram Jaccard）
MAX_ITEM_CHARS = 120        # 单条知识压成一行时保留的长度
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_PASSAGE_HEAD = "相关知识："
_SPACE_RE = re.compile(r"\s+")
_CLEAN_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def _clean(text):
    """压成一行：知识条目在提示词里必须是一条，不能带换行。"""
    return _SPACE_RE.sub(" ", str(text or "")).strip()


def _text(item):
    if not isinstance(item, dict):
        return ""
    return _clean(item.get("text") or item.get("content") or "")


def _grams(text):
    """字符 bigram（中英数字统一）：用于相似度与词面重合。"""
    body = _CLEAN_RE.sub("", str(text or "").lower())
    if len(body) < 2:
        return {body} if body else set()
    return {body[i:i + 2] for i in range(len(body) - 1)}


def jaccard(a, b):
    """两条文本的 bigram Jaccard（0..1）；空文本按"不相似"。"""
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(len(ga | gb))


def overlap(query, text):
    """查询词面被文本覆盖的比例（BM25 的极简替身，0..1）。"""
    q = _grams(query)
    if not q:
        return 0.0
    return len(q & _grams(text)) / float(len(q))


def _base_score(item):
    try:
        value = float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(1.0, value))


def relevance(item, query):
    """融合相关度：六成来源分数 + 四成词面重合（缺哪项就用另一项）。"""
    base = _base_score(item)
    try:
        lex = float(item.get("lexical_overlap") or -1.0)
    except (TypeError, ValueError):
        lex = -1.0
    if lex < 0:
        lex = overlap(query, _text(item))
    return round(0.6 * base + 0.4 * max(0.0, min(1.0, lex)), 4)


def _merge(keep, extra):
    """把重复条目并进保留项：来源合并、分数取高。"""
    merged = dict(keep)
    sources = list(keep.get("sources") or [])
    for src in [keep.get("source")] + \
            list(extra.get("sources") or [extra.get("source")]):
        src = _clean(src)
        if src and src not in sources:
            sources.append(src)
    merged["sources"] = sources
    merged["source"] = "、".join(sources) if sources else keep.get("source", "")
    merged["score"] = max(_base_score(keep), _base_score(extra))
    return merged


def dedupe(items, threshold=DEFAULT_DEDUP):
    """近似重复合并：保留分高者，并把两条的来源合并成 "记忆、知识库"。"""
    kept = []
    for item in items or []:
        if not isinstance(item, dict) or not _text(item):
            continue
        dup = None
        for other in kept:
            if jaccard(_text(item), _text(other)) >= float(threshold):
                dup = other
                break
        if dup is None:
            kept.append(item)
            continue
        idx = kept.index(dup)
        kept[idx] = _merge(dup, item)          # 同名不同来源 → 合并保留
    return kept


def mmr(items, top_k=DEFAULT_TOP_K, lambda_=DEFAULT_LAMBDA):
    """最大边际相关：先挑最相关，之后每条都"扣掉与已选的相似度"。"""
    limit = max(0, int(top_k or 0))
    if not limit:
        return []
    pool = [item for item in (items or [])
            if isinstance(item, dict) and _text(item)]
    if not pool:
        return []
    left = list(pool)
    picked = [max(left, key=lambda it: float(it.get("relevance") or 0.0))]
    left.remove(picked[0])
    while left and len(picked) < limit:
        best, best_value = None, None
        for item in left:
            rel = float(item.get("relevance") or 0.0)
            sim = max(jaccard(_text(item), _text(sel)) for sel in picked)
            value = float(lambda_) * rel - (1.0 - float(lambda_)) * sim
            if best_value is None or value > best_value:
                best, best_value = item, value
        picked.append(best)
        left.remove(best)
    return picked[:limit]


def rerank(query, items, top_k=DEFAULT_TOP_K, lambda_=DEFAULT_LAMBDA,
           dedup=DEFAULT_DEDUP):
    """统一入口：清洗 → 融合打分 → 排序 → 去重 → MMR → 截断。

    返回的每条都带 ``relevance``（融合分）、``source``（来源，可能合并过）。
    """
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = _text(item)
        if not text:
            continue
        row = dict(item)
        row["text"] = text[:MAX_ITEM_CHARS]
        row["relevance"] = relevance(row, query)
        cleaned.append(row)
    cleaned.sort(key=lambda it: (-float(it.get("relevance") or 0.0),
                                 _text(it)))
    kept = dedupe(cleaned, threshold=dedup)
    return mmr(kept, top_k=top_k, lambda_=lambda_)


def format_passages(items, limit=DEFAULT_TOP_K, show_source=True):
    """拼成 ``相关知识：\n① …（来源：记忆）``；空列表返回空串。"""
    rows = [it for it in (items or []) if isinstance(it, dict) and _text(it)]
    if not rows:
        return ""
    lines = [_PASSAGE_HEAD]
    for index, item in enumerate(rows[:max(1, int(limit or 1))], 1):
        mark = CIRCLED[index - 1] if index <= len(CIRCLED) else "%d." % index
        text = _text(item)[:MAX_ITEM_CHARS]
        source = _clean(item.get("source") or "")
        suffix = ("（来源：%s）" % source) if (show_source and source) else ""
        lines.append("%s %s%s" % (mark, text, suffix))
    return "\n".join(lines)
