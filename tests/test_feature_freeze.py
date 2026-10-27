# -*- coding: utf-8 -*-
"""冻结守卫测试：Feature / 模块文件 / 按钮 / 覆盖率门槛只许降不许升。"""
import copy
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from tools.check_feature_freeze import (  # noqa: E402
    compare,
    load_baseline,
    main,
    snapshot,
)


def test_baseline_and_current_are_consistent():
    baseline = load_baseline()
    assert baseline["active"] is True
    assert baseline["features"] == 46
    assert baseline["button_total"] <= 184
    assert baseline["coverage_thresholds"]["global"]["minimum"] >= 60.0
    assert baseline["coverage_thresholds"]["directory_minimums"]["core"] >= 57.0

    current = snapshot()
    errors, _warnings = compare(current, baseline)
    assert not errors


def test_new_feature_is_rejected():
    baseline = load_baseline()
    current = copy.deepcopy(snapshot())
    current["features"] = baseline["features"] + 1
    errors, _warnings = compare(current, baseline)
    assert any("Feature 数增加" in item for item in errors)


def test_new_module_file_is_rejected():
    baseline = load_baseline()
    for key, label in (("core_files", "core"), ("gui_files", "gui")):
        current = copy.deepcopy(snapshot())
        current[key] = baseline[key] + 1
        errors, _warnings = compare(current, baseline)
        assert any("%s/ 模块文件数增加" % label in item for item in errors)


def test_button_budget_increase_is_rejected():
    baseline = load_baseline()
    current = copy.deepcopy(snapshot())
    current["button_total"] = baseline["button_total"] + 1
    errors, _warnings = compare(current, baseline)
    assert any("按钮预算增加" in item for item in errors)


def test_lowered_coverage_threshold_is_rejected():
    baseline = load_baseline()
    current = copy.deepcopy(snapshot())
    current["coverage_thresholds"]["global"]["minimum"] -= 1.0
    errors, _warnings = compare(current, baseline)
    assert any("覆盖率门槛被下调" in item for item in errors)


def test_check_cli_passes():
    assert main(["--check"]) == 0
