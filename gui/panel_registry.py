# -*- coding: utf-8 -*-
"""Single source of truth for panel/command entries.

The command palette and settings window share this mapping. A missing owner
callback is intentionally represented as None so the UI can disable it.
"""


def build_panel_commands(owner):
    def get(name):
        return getattr(owner, name, None)

    return {
        "电脑控制": get("computer_dialog"),
        "机器人": get("bot_dialog"),
        "插件市场": get("plugin_dialog"),
        "MCP市场": get("mcp_dialog"),
        "历史记录": get("history_dialog"),
        "日志中心": get("log_dialog"),
        "系统自检": get("sys_dialog"),
        "首次设置向导": get("onboarding_dialog"),
        "模型管理": get("model_manager_dialog"),
        "语音对话": get("voice_chat_dialog"),
        "记忆可视化": get("memory_view_dialog"),
        "数据统计": get("stats_dialog"),
        "日历待办": get("tools_dialog"),
        "搜索聊天": get("search_dialog"),
        "安全中心": get("security_center_dialog"),
        "任务中心": get("open_task_center"),
        "运行中活动": get("activity_center_dialog"),
        "代码 Agent": get("code_agent_dialog"),
        "知识库": get("kb_dialog"),
        "RAG管理": get("rag_dialog"),
        "团队管理": get("team_dialog"),
        "多用户": get("team_dialog"),
        "用量成本": get("usage_dialog"),
        "模型用量": get("usage_dialog"),
        "资料中心": get("kb_dialog"),
        "检查更新": get("update_dialog"),
        "桌宠": get("pet_dialog"),
        "模块星图": get("module_map_dialog"),
        "意见反馈": get("show_feedback"),
        "新手教程": get("show_tutorial"),
        "可选组件": get("show_components"),
        "设置": get("set_dialog"),
        "命令面板 (Ctrl+K)": get("command_palette"),
        "实用工具（旧按钮面板）": get("module_tools_dialog"),
    }
