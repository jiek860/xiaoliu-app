# -*- coding: utf-8 -*-
"""D4 体检报告 单元测试（功能深化二期）。"""
from core import health_report as hr


def test_status_from_ok():
    assert hr.status_from_ok(True) == hr.PASS
    assert hr.status_from_ok(True, warn=True) == hr.WARN
    assert hr.status_from_ok(False) == hr.FAIL


def test_overall_status():
    assert hr.overall_status([{"status": "pass"}]) == hr.PASS
    assert hr.overall_status([{"status": "warn"}]) == hr.WARN
    assert hr.overall_status([{"status": "warn"}, {"status": "fail"}]) == hr.FAIL


def test_summarize_counts():
    items = [{"status": "pass"}, {"status": "warn"}, {"status": "fail"},
             {"status": "fail"}]
    s = hr.summarize(items)
    assert s["pass"] == 1 and s["warn"] == 1 and s["fail"] == 2
    assert s["overall"] == hr.FAIL


def test_build_report_bool_and_dict():
    rep = hr.build_report([
        ("模型", lambda: True),
        ("存储", lambda: {"ok": False, "hint": "空间不足"}),
        ("安全", lambda: {"ok": True, "warn": True, "hint": "建议加固"}),
    ])
    assert rep["overall"] == hr.FAIL
    hints = {i["name"]: i["hint"] for i in rep["items"]}
    assert hints["存储"] == "空间不足"


def test_build_report_check_exception():
    def boom():
        raise RuntimeError("炸了")
    rep = hr.build_report([("坏检查", boom)])
    assert rep["overall"] == hr.FAIL
    assert "检查异常" in rep["items"][0]["hint"]