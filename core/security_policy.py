# -*- coding: utf-8 -*-
"""统一工具安全策略。

工具表里的 readonly/confirm/danger 只是声明；真正执行前必须在这里
做一次默认拒绝式判断。未登记的工具默认按高风险处理。
"""
from __future__ import annotations

# 内置工具的风险默认值。插件/core 能力仍以声明字段为准，但未声明时
# classify() 会把它归为需要确认。
BUILTIN_RISK = {
    "deep_search": {"risk": "network", "readonly": True},
    "vector_search": {"risk": "read", "readonly": True},
    "graph_query": {"risk": "read", "readonly": True},
    "task_plan": {"risk": "read", "readonly": True},
    "fs_search": {"risk": "read", "readonly": True},
    "ui_find": {"risk": "read", "readonly": True},
    "ui_dump": {"risk": "read", "readonly": True},
    "file_read": {"risk": "read_sensitive", "confirm": True},
    "fs_read": {"risk": "read_sensitive", "confirm": True},
    "code_run": {"risk": "exec", "confirm": True, "danger": True,
                 "danger_rule": "工具.允许代码执行"},
    "fs_edit": {"risk": "write", "confirm": True, "danger": True,
                "danger_rule": "工具.允许文件修改"},
    "computer": {"risk": "ui_control", "confirm": True},
    "browser": {"risk": "ui_network", "confirm": True},
    "ui_click": {"risk": "ui_control", "confirm": True},
    "shell": {"risk": "exec", "confirm": True, "danger": True,
              "danger_rule": "电脑控制.允许命令"},
}

DANGEROUS_METHOD_PREFIXES = (
    "code_runner.", "computer_controller.", "file_upload.",
    "plugin_market.", "auto_updater.", "hot_reload.", "browser.",
    "mcp_server.", "trunk.", "memory_crypto.", "memory_organizer.",
    "memory_archiver.", "data_cleaner.", "migration.",
    "personality_market.", "browser_session.", "action_recorder.",
    "scheduler.", "learning_loop.", "task_loop.", "task_planner.",
    "auto_report.", "crash_export.", "personality.", "knowledge_qa.",
    "notes.", "todo.", "calendar.", "group_chat.", "group_loop.",
    "group_parallel.", "voice.", "tts.", "realtime_chat.",
)


def classify(tool_name, info=None):
    """返回规范化后的策略 dict。未登记/异常 -> 默认需要确认。"""
    info = info or {}
    out = {"risk": "write", "readonly": False, "confirm": True,
           "danger": False, "danger_rule": ""}
    out.update(BUILTIN_RISK.get(str(tool_name), {}))
    for key in ("risk", "readonly", "confirm", "danger", "danger_rule"):
        if key in info and info.get(key) is not None:
            out[key] = info.get(key)
    # 插件/core 能力经常只声明 readonly=True。此时没有显式 confirm/danger
    # 就表示只读免确认。内置高风险工具在 BUILTIN_RISK 里已经显式
    # confirm=True，不会被这条覆盖。
    if info.get("readonly") and "confirm" not in info and "danger" not in info:
        out["confirm"] = False
        out["risk"] = out.get("risk") or "read"
    # 未知工具：强制确认。
    if not info.get("readonly") and not info.get("confirm") and not info.get("danger"):
        out["confirm"] = True
    return out


def needs_confirm(tool_name, info=None):
    p = classify(tool_name, info)
    return bool(p.get("confirm") or p.get("danger"))


def danger_rule(tool_name, info=None):
    p = classify(tool_name, info)
    if not p.get("danger"):
        return ""
    return str(p.get("danger_rule") or "电脑控制.允许命令")


def remote_safe(tool_name, info=None):
    """HTTP/MCP 等远程入口默认只允许无副作用的只读工具。"""
    p = classify(tool_name, info)
    method = str((info or {}).get("method") or "")
    if method.startswith(DANGEROUS_METHOD_PREFIXES):
        return False
    return bool(p.get("readonly")) and not p.get("confirm") and not p.get("danger")


def method_is_dangerous(method):
    return str(method or "").startswith(DANGEROUS_METHOD_PREFIXES)
