# -*- coding: utf-8 -*-
"""工具候选融合与排序（功能深化二期 · E1 工具选择）。

工具选择原来是「关键词粗筛 + 相似度精排」两级。这里补上：

* ``fuse``：把"关键词分"和可选的"语义分"按权重融合；
* ``rank``：先按分数降序，同分按风险升序（只读工具优先），再按名字稳定排序。

纯函数，不依赖 trunk，方便接进 ``core/tool_caller.py`` 也可单测。
"""
from __future__ import annotations

_RISK_ORDER = {"read": 0, "low": 0, "medium": 1, "high": 2,
               "danger": 3, "dangerous": 3}


def risk_level(risk):
    return _RISK_ORDER.get(str(risk or "").strip().lower(), 1)


def fuse(keyword, semantic, kw_weight=1.0, sem_weight=1.5):
    """融合两路打分：{name: 权重*关键词分 + 权重*语义分}。"""
    keyword = keyword or {}
    semantic = semantic or {}
    names = set(keyword) | set(semantic)
    return {
        n: float(keyword.get(n, 0.0)) * float(kw_weight)
        + float(semantic.get(n, 0.0)) * float(sem_weight)
        for n in names
    }


def rank(candidates, score_of=None, risk_of=None):
    """candidates 为工具名列表；返回排序后的列表。"""
    candidates = list(candidates or [])
    score_of = score_of or (lambda n: 0.0)
    risk_of = risk_of or (lambda n: "low")
    return sorted(
        candidates,
        key=lambda n: (-float(score_of(n)), risk_level(risk_of(n)), str(n)))


def pick(keyword, semantic=None, risk_of=None, top_k=8):
    """融合后取 TopK（按 rank 规则）。"""
    scores = fuse(keyword, semantic)
    return rank(list(scores), score_of=lambda n: scores.get(n, 0.0),
                risk_of=risk_of)[:max(1, int(top_k))]