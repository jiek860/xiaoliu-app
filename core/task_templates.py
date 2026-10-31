# -*- coding: utf-8 -*-
"""任务模板与自然语言定时解析（功能深化二期 · B1 任务编排）。

两块纯逻辑，不依赖 Qt：

* **模板**：常用任务（周报 / 代码审查 / 资料整理）存成一条 ``goal``，
  一键实例化成 TaskRuntime 任务，免去每次重写目标。
* **定时解析**：把「每天 9 点 / 每周五 9:00 / 每小时」这类说法
  解析成结构化 dict，交给调度侧使用（本模块只解析，不跑定时器）。

设计约束
--------
* ``instantiate`` 只调用 ``TaskRuntime.create``，不启动线程，调用方自行 start。
* 解析失败返回 ``{}``，让上层可以退化成"不定时"而不是报错。
"""
from __future__ import annotations

import re

# 内置模板：name -> {goal, mode}
TEMPLATES = {
    "周报总结": {"goal": "总结本周工作进展，按项目/完成/待办生成周报", "mode": "agent"},
    "代码审查": {"goal": "审查最近改动的代码，列出问题、风险与改进建议", "mode": "agent"},
    "资料整理": {"goal": "整理指定资料，去重并生成结构化摘要", "mode": "agent"},
    "会议纪要": {"goal": "根据给定记录整理会议纪要：结论、待办、负责人", "mode": "agent"},
}

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6,
             "天": 6}


def list_templates():
    return sorted(TEMPLATES.keys())


def get_template(name):
    """按名字取模板；不存在返回 {}。"""
    return dict(TEMPLATES.get(str(name or "").strip()) or {})


def instantiate(runtime, name, *, depends_on=None, schedule_text=None):
    """用模板创建任务（不启动）。返回 task dict；模板不存在返回 {}。"""
    tpl = get_template(name)
    if not tpl:
        return {}
    task = runtime.create(
        tpl.get("goal", ""),
        mode=tpl.get("mode", "agent"),
        depends_on=depends_on,
        template=str(name or ""),
        schedule=parse_schedule(schedule_text) if schedule_text else {},
    )
    return task


def _hm(text):
    m = re.search(r"([0-9]{1,2})[:：]([0-9]{2})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"([0-9]{1,2})\s*点", text)
    if m:
        return int(m.group(1)), 0
    return 0, 0


def parse_schedule(text):
    """把自然语言定时解析成结构化 dict；解析不出返回 {}。

    支持：每小时 / 每天 X 点 / 每天 X:MM / 每周X X 点
    """
    s = str(text or "")
    if not s:
        return {}
    if "每小时" in s or "每钟头" in s:
        return {"kind": "hourly"}
    if "每天" in s or "每日" in s:
        hour, minute = _hm(s)
        return {"kind": "daily", "hour": hour, "minute": minute}
    m = re.search(r"每(?:周|星期)([一二三四五六日天])", s)
    if m:
        hour, minute = _hm(s)
        return {"kind": "weekly", "weekday": _WEEKDAYS[m.group(1)],
                "hour": hour, "minute": minute}
    return {}