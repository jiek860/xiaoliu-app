# -*- coding: utf-8 -*-
"""批次 49.1：开关矩阵覆盖与基线探针。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.ab_matrix import (SWITCHES, _matches, pairwise_cases,  # noqa: E402
                             _probe, cartesian_cases)


def test_pairwise_covers_every_two_switch_combination():
    cases = pairwise_cases(SWITCHES)
    assert cases
    assert len(cases) < 80
    covered = set()
    for case in cases:
        covered |= set(_matches(case))
    for i, left in enumerate(SWITCHES):
        for value in left["values"]:
            assert (i, value) in covered
        for j in range(i + 1, len(SWITCHES)):
            for lv in left["values"]:
                for rv in SWITCHES[j]["values"]:
                    assert (i, lv, j, rv) in covered


def test_default_case_first_and_probes_pass():
    default = [s["default"] for s in SWITCHES]
    checks = _probe(default, SWITCHES)
    assert all(passed for _, passed in checks)


def test_cartesian_guard():
    cases = cartesian_cases(SWITCHES[:2])
    assert len(cases) == len(SWITCHES[0]["values"]) * len(SWITCHES[1]["values"])
    try:
        cartesian_cases(SWITCHES, limit=10)
    except ValueError as exc:
        assert "上限" in str(exc)
    else:
        raise AssertionError("超限笛卡尔积应被拒绝")
