# -*- coding: utf-8 -*-
"""B1 任务模板 / 定时解析 / 任务级依赖 单元测试（功能深化二期）。"""
from types import SimpleNamespace

from core import task_templates
from core.task_runtime import TaskRuntime


def _rt(tmp_path):
    return TaskRuntime(SimpleNamespace(base=str(tmp_path)))


def test_parse_schedule_variants():
    assert task_templates.parse_schedule("每小时") == {"kind": "hourly"}
    assert task_templates.parse_schedule("每天9点") == {
        "kind": "daily", "hour": 9, "minute": 0}
    assert task_templates.parse_schedule("每天 08:30") == {
        "kind": "daily", "hour": 8, "minute": 30}
    assert task_templates.parse_schedule("每周五 9:00") == {
        "kind": "weekly", "weekday": 4, "hour": 9, "minute": 0}
    assert task_templates.parse_schedule("随便说说") == {}
    assert task_templates.parse_schedule("") == {}


def test_templates_list_and_instantiate(tmp_path):
    rt = _rt(tmp_path)
    assert "周报总结" in task_templates.list_templates()
    task = task_templates.instantiate(rt, "周报总结")
    assert task["template"] == "周报总结"
    assert task["goal"]
    assert task_templates.instantiate(rt, "不存在的模板") == {}


def test_instantiate_with_schedule(tmp_path):
    rt = _rt(tmp_path)
    task = task_templates.instantiate(rt, "代码审查", schedule_text="每天 9:00")
    assert task["schedule"] == {"kind": "daily", "hour": 9, "minute": 0}


def test_task_dependency_blocks_start(tmp_path):
    rt = _rt(tmp_path)
    t1 = rt.create("前置任务")
    t2 = rt.create("后置任务", depends_on=[t1["id"]])
    ok, why = rt.can_start(t2["id"])
    assert ok is False and "前置" in why
    rt._tasks[t1["id"]]["status"] = "completed"
    rt._save(rt._tasks[t1["id"]])
    ok2, _why = rt.can_start(t2["id"])
    assert ok2 is True


def test_can_start_missing_dep(tmp_path):
    rt = _rt(tmp_path)
    t = rt.create("x", depends_on=["no_such_task"])
    ok, why = rt.can_start(t["id"])
    assert ok is False and "不存在" in why