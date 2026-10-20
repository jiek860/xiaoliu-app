# -*- coding: utf-8 -*-
"""文件长度策略测试：目标区间、500 警告、600 失败、800 冻结。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from tools.check_file_sizes import evaluate, load_policy, scan  # noqa: E402


def test_file_size_policy_thresholds():
    policy, budgets = load_policy()
    assert policy["default_max_lines"] == 600
    assert policy["warn_lines"] == 500
    assert policy["block_new_code_lines"] == 800
    assert policy["targets"]["ordinary"] == [200, 400]
    assert policy["targets"]["core_complex"] == [300, 450]

    rows = [
        (350, "core/normal.py"),
        (450, "core/complex.py"),
        (550, "core/warn.py"),
        (600, "core/exact_limit.py"),
        (650, "core/too_big.py"),
        (900, "core/legacy.py"),
    ]
    p = dict(policy)
    b = {"core/legacy.py": {"budget": 900, "status": "legacy_blocked"}}
    errors, warnings, blocked = evaluate(rows, p, b)
    assert any("exact_limit.py" in x[1] for x in errors)
    assert any("too_big.py" in x[1] for x in errors)
    assert any("warn.py" in x[1] for x in warnings)
    assert any("legacy.py" in x[1] for x in blocked)


def test_current_repo_within_budgets():
    policy, budgets = load_policy()
    errors, _warnings, _blocked = evaluate(scan(), policy, budgets)
    assert not errors
