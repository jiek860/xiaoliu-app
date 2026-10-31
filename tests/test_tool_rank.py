# -*- coding: utf-8 -*-
"""E1 工具选择融合/排序 单元测试（功能深化二期）。"""
from core import tool_rank


def test_fuse_combines_scores():
    kw = {"search": 1.0, "calc": 0.5}
    sem = {"search": 0.2, "code": 0.9}
    fused = tool_rank.fuse(kw, sem, kw_weight=1.0, sem_weight=1.5)
    assert set(fused) == {"search", "calc", "code"}
    assert abs(fused["search"] - (1.0 + 0.3)) < 1e-9
    assert abs(fused["code"] - 1.35) < 1e-9


def test_rank_score_then_risk():
    names = ["a", "b", "c"]
    scores = {"a": 1.0, "b": 2.0, "c": 1.0}
    risks = {"a": "high", "b": "low", "c": "low"}
    out = tool_rank.rank(names, score_of=lambda n: scores[n],
                         risk_of=lambda n: risks[n])
    # b 分最高；a/c 同分，c 风险低优先于 a
    assert out == ["b", "c", "a"]


def test_pick_top_k():
    kw = {"t1": 3.0, "t2": 2.0, "t3": 1.0}
    out = tool_rank.pick(kw, top_k=2)
    assert out == ["t1", "t2"]


def test_risk_level_mapping():
    assert tool_rank.risk_level("read") == 0
    assert tool_rank.risk_level("danger") == 3
    assert tool_rank.risk_level("weird") == 1