# -*- coding: utf-8 -*-
"""Golden Set 代码门禁：patch 应用 → fixture check.py 通过率不得下降。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

import golden_runner as gr  # noqa: E402


def test_code_cases_exist():
    cases = gr.load_cases("code")
    assert len(cases) >= 5
    for case in cases:
        assert case.get("fixture") and case.get("patch")


def test_code_pass_rate_not_below_baseline():
    result = gr.run_domain("code")
    problems = gr.regressions("code", result)
    assert problems == [], "代码通过率下降：" + "；".join(problems)


def test_broken_patch_is_rejected_without_writing():
    """打错的 hunk 必须在预演阶段被拦下，不能写坏 fixture。"""
    case = {"id": "bad", "fixture": "tests/fixtures/code/calc",
            "patch": {"files": [{"op": "update", "path": "calc.py",
                                 "hunks": [{"old": "不存在的原文", "new": "x"}]}]}}
    row = gr.score_code_case(case)
    assert not row["ok"]
    assert "patch 应用失败" in row["issues"][0]
