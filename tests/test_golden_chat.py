# -*- coding: utf-8 -*-
"""Golden Set 聊天门禁：分数不得低于基线（允许小幅抖动）。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

import golden_runner as gr  # noqa: E402


def test_chat_cases_exist_and_cover_three_kinds():
    cases = gr.load_cases("chat")
    assert len(cases) >= 10
    kinds = {c.get("kind") for c in cases}
    assert {"retrieval", "referent", "reply"} <= kinds


def test_chat_scores_not_below_baseline():
    result = gr.run_domain("chat")
    problems = gr.regressions("chat", result)
    assert problems == [], "聊天分数下降：" + "；".join(problems)


def test_chat_metrics_are_tracked():
    result = gr.run_domain("chat")
    for key in ("memory_hit_rate", "citation_accuracy",
                "referent_accuracy", "style_pass_rate"):
        assert key in result["metrics"]


def test_retrieval_never_fabricates_without_evidence():
    """无关问题必须返回空结果，不能硬凑记忆（宁缺毋滥）。"""
    case = {"query": "珠穆朗玛峰有多高", "top_k": 3,
            "corpus": [{"id": "a", "text": "用户喜欢美式咖啡", "source": "记忆"}],
            "expect": {"empty": True}}
    row = gr.score_chat_case(case)
    assert row["ok"], row["issues"]
