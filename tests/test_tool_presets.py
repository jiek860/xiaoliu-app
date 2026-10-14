# -*- coding: utf-8 -*-
"""工具模式预设的回归保护（core/tool_presets.py）

补这笔欠账的原因
----------------
模式预设（日常/干活/编程/维护）是 v25.2.0 加的关键逻辑，当时只用**临时脚本**
验了 24 项就完事了，**没留下永久测试**。这一整轮我一直在批评"写好了没人验"，
结果自己犯了同一个错。

守住四件事
    ① 默认必须是"全部"= 不过滤（零行为变化）
    ② 每个模式的收窄结果符合预期（该有的有、该没有的没有）
    ③ 切换后 _candidates 真的跟着变
    ④ 三重防御：模式名不认识 / 为 None / 过滤后为空 —— 都不能把能力搞没
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core import tool_presets                      # noqa: E402
from core.trunk import Trunk                       # noqa: E402
from tests.conftest import make_trunk              # noqa: E402


@pytest.fixture(scope="module")
def tc():
    """工具表（用 make_trunk：裸 Trunk 会连 MCP 拉子进程）"""
    t = make_trunk()
    return t, t._load_lazy("tool_caller")


# ── ① 默认不过滤 ──
def test_default_preset_is_all():
    """默认必须是"全部" —— 行为与加这个机制之前完全一致"""
    t = make_trunk()
    re_ = t._load_lazy("rules_engine")
    assert re_.get("工具.模式") == "全部", \
        "规则默认值不是'全部'：%s" % re_.get("工具.模式")
    assert tool_presets.current(t) == "全部"


def test_source_default_is_all_not_just_runtime():
    """**源码里的默认值**也必须是"全部"

    为什么单独查这个：上面那条读的是**运行时值**，而运行时的值来自
    data/rules/rules.json（已持久化）。所以把 rules_engine.py 里的默认值
    改掉时，**老用户不受影响（值已落盘）**，但**新用户一装就是错的模式** ——
    上面那条测试抓不到这种"只影响新装环境"的改动。

    （这条是负向测试发现的：我把源码默认改成"编程"，上面那条照样通过。）
    """
    import ast
    p = os.path.join(BASE, "core", "rules_engine.py")
    tree = ast.parse(open(p, encoding="utf-8").read())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "register"):
            continue
        args = node.args
        if not args or not (isinstance(args[0], ast.Constant)
                            and args[0].value == "工具.模式"):
            continue
        # register(名字, 组, 类型, 说明, 默认值) —— 默认值是最后一个参数
        last = args[-1]
        found.append(last.value if isinstance(last, ast.Constant) else "?")
    assert found, "在 rules_engine.py 里找不到「工具.模式」的注册"
    assert found[-1] == "全部", \
        "源码默认值是 %r，应为 '全部' —— 老用户不受影响，" \
        "但**新装的环境一上来就是错的模式**" % (found[-1],)


def test_all_preset_does_not_filter(tc):
    _t, c = tc
    d = tool_presets.describe(c.tools, "全部")
    assert d["过滤掉"] == 0, d
    assert d["该模式可用"] == d["工具数"]


# ── ② 各模式的收窄符合预期 ──
CASES = [
    ("日常", "weather_now", True), ("日常", "todo_add", True),
    ("日常", "note_add", True), ("日常", "fs_edit", False),
    ("日常", "shell", False),
    ("干活", "fs_read", True), ("干活", "ui_click", True),
    ("干活", "shell", True), ("干活", "weather_now", False),
    ("编程", "code_run", True), ("编程", "shell", True),
    ("编程", "fs_edit", True), ("编程", "todo_add", False),
    ("维护", "memory_organize", True), ("维护", "clean_data", True),
    ("维护", "ui_click", False),
]


@pytest.mark.parametrize("preset,tool,expect", CASES,
                         ids=["%s-%s" % (p, t) for p, t, _ in CASES])
def test_preset_membership(preset, tool, expect):
    got = tool_presets.match(tool, preset)
    assert got is expect, \
        "%s 模式下 %s 应为 %s，实际 %s" % (preset, tool, expect, got)


def test_every_preset_narrows_but_keeps_something(tc):
    """每个非"全部"的模式都要真的收窄，但不能一个都不剩"""
    _t, c = tc
    for name in tool_presets.names():
        if name == "全部":
            continue
        d = tool_presets.describe(c.tools, name)
        assert d["过滤掉"] > 0, "%s 模式没有收窄任何东西" % name
        assert d["该模式可用"] > 0, "%s 模式把工具全滤没了" % name


# ── ③ 切换后真的生效 ──
def test_switching_preset_changes_candidates(tc):
    t, c = tc
    re_ = t._load_lazy("rules_engine")
    try:
        re_.set("工具.模式", "编程", persist=True)
        prog = c._candidates("帮我写个 Python 脚本")
        assert not any(k in prog for k in
                       ("weather_now", "todo_add", "note_add")), \
            "编程模式下还能选到日常能力：%s" % list(prog)[:6]

        re_.set("工具.模式", "日常", persist=True)
        daily = c._candidates("杭州今天天气怎么样")
        assert "weather_now" in daily, "日常模式下选不到天气：%s" % list(daily)[:6]
        assert "shell" not in daily, "日常模式下不该有 shell"
    finally:
        re_.reset_rule("工具.模式")


# ── ④ 三重防御 ──
def test_unknown_preset_does_not_filter(tc):
    _t, c = tc
    got = tool_presets.filter_tools(c.tools, "乱写的模式名")
    assert len(got) == len(c.tools), "不认识的名字把工具滤掉了"


def test_none_preset_does_not_filter(tc):
    _t, c = tc
    assert len(tool_presets.filter_tools(c.tools, None)) == len(c.tools)


def test_empty_result_falls_back_to_all():
    """过滤后为空必须原样返回 —— 过滤错会让模型'没有这个能力'，
    比'多给几个候选'严重得多"""
    fake = {"zzz_不存在的能力": {"desc": "x"}}
    got = tool_presets.filter_tools(fake, "编程")
    assert len(got) == 1, "全被滤掉时没退回原样：%s" % got


def test_prefix_matching_covers_new_tools():
    """按前缀匹配 —— 以后新加的 todo_xxx 应自动归入对应模式"""
    assert tool_presets.match("todo_whatever_new", "日常"), \
        "前缀匹配失效了，新加的同族工具不会自动归类"


def test_preset_names_are_stable():
    """模式名是对外契约（规则里存的就是它），不能悄悄改名"""
    assert set(tool_presets.names()) == {"全部", "日常", "干活", "编程", "维护"}
