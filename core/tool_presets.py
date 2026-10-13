# -*- coding: utf-8 -*-
"""工具模式预设 —— 按场景收窄工具表

为什么要收窄
------------
实测 `_llm_decide` 的提示词：工具表 53 个时不筛选要 3127 字符。
虽然有 hints 粗筛把它压到 889 字符以内，但**候选里混着不相关的能力**
仍然会拉低模型的选择准确率（工具越多越容易挑错）。

DSH 用 agent preset（minimal / standard / ptc）解决同一问题，
豆包用"工作任务"这种模式切换解决。这里是它们的合体：
**一个模式 = 一组相关的工具**，用户按场景切。

设计原则
--------
    · **默认"全部"**，不过滤 —— 行为与改动前完全一致
    · 匹配用**名字前缀/精确名**，不写死具体清单，新能力加进来能自动归类
    · 模式只影响**进 LLM 候选的范围**，不影响命令面板里能搜到什么
      （面板始终显示全部 —— 收窄是给模型减负，不是给用户减功能）

与规则引擎的关系
----------------
活动模式存在规则「工具.模式」里（默认 "全部"），落盘 data/rules/rules.json，
和「电脑控制.允许命令」那套是同一个机制，不用另造一套配置。
"""

# 模式 -> 允许的工具名前缀（None 表示不过滤）
PRESETS = {
    "全部": None,

    # 日常问答：查资料、记事、看统计 —— 不碰文件系统和命令
    "日常": [
        "vector_search", "graph_query", "deep_search",
        "weather_now", "todo_", "note_", "calendar_", "translate_",
        "stats_report", "mood_report", "growth_report", "grouploop_",
        "dream_", "memory_conflicts", "memory_archives",
    ],

    # 干活：操作电脑、看界面、跑命令、动文件
    "干活": [
        "fs_", "browser", "shell", "ui_", "code_run", "computer",
        "task_plan", "deep_search", "file_read", "action_recordings",
    ],

    # 编程：只留工程向的，联网搜索和日常功能都收起
    "编程": [
        "fs_", "code_run", "shell", "browser", "mcp_run_code",
        "task_plan", "deep_search",
    ],

    # 维护：记忆整理、数据清理、导出、体检
    "维护": [
        "memory_", "clean_data", "migrate_export", "crash_export",
        "personality_export", "gpu_check", "stats_report",
        "browser_sessions", "ocr_available",
    ],
}


def names():
    """所有可用模式名"""
    return list(PRESETS)


def match(tool_name, preset):
    """这个工具在不在该模式里

    preset 为 None / "全部" / 不认识的名字 -> 一律通过（宁可多给，不可少给：
    过滤错会让模型"没有这个能力"，比"多给几个候选"严重得多）。
    """
    pats = PRESETS.get(preset)
    if not pats:
        return True
    n = str(tool_name or "")
    for p in pats:
        if n == p or n.startswith(p):
            return True
    return False


def filter_tools(tools, preset):
    """按模式过滤 {名: 声明}；过滤后为空则原样返回（防止把能力全滤没了）"""
    try:
        if not PRESETS.get(preset):
            return tools
        out = {k: v for k, v in tools.items() if match(k, preset)}
        return out or tools
    except Exception:
        return tools


def current(trunk):
    """读当前模式（规则引擎 → config → 默认全部）"""
    try:
        v = trunk.rule("工具.模式", None) if trunk else None
        if v and v in PRESETS:
            return v
    except Exception:
        pass
    try:
        v = (getattr(trunk, "config", {}) or {}).get("工具模式")
        if v and v in PRESETS:
            return v
    except Exception:
        pass
    return "全部"


def describe(tools, preset):
    """给自检用：这个模式下能进候选多少个"""
    f = filter_tools(tools, preset)
    return {"模式": preset, "工具数": len(tools), "该模式可用": len(f),
            "过滤掉": len(tools) - len(f)}
