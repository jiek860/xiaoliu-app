# -*- coding: utf-8 -*-
"""统一 UI 功能注册表。

这个模块只描述功能是什么、属于哪一组、在哪种模式可见，不依赖 Qt。
主窗口、命令面板、设置窗口和测试都用同一份数据，避免一个入口改了、
另一个入口还停留在旧状态。

设计约束
--------
* 简单模式只暴露普通用户真正需要的入口（首屏主要按钮 <= 7）。
* 高级模式不删除任何能力，只是把低频入口从首屏移到头像/更多菜单。
* 每个入口都有稳定的 id、分组、可见模式，方便加功能时先过预算。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

SIMPLE = "simple"
ADVANCED = "advanced"
MODES = (SIMPLE, ADVANCED)

# 命令面板分组顺序（需求：常用、任务、资料、工具、安全、插件/MCP、开发）
COMMAND_GROUPS: Tuple[str, ...] = (
    "常用", "任务", "资料", "工具", "安全", "插件/MCP", "开发",
)


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    icon: str = ""
    group: str = "常用"              # 命令面板分组
    modes: Tuple[str, ...] = MODES  # 在哪些 UI 模式可见
    order: int = 100
    primary: bool = False            # 是否计入首屏主要按钮
    description: str = ""
    attr: str = ""                   # 主窗口控件属性名（可选）
    action: str = ""                 # 主窗口方法名（可选）

    def visible_in(self, mode: str) -> bool:
        return mode in self.modes


_FEATURES = [
    # ---------- 简单模式首屏 ----------
    Feature("new_chat", "新建对话", "＋", "常用", MODES, 10, True,
            "创建一个新的聊天会话", "new_chat_btn", "_new_session"),
    Feature("chat", "对话", "💬", "常用", MODES, 20, False,
            "回到聊天输入框", "nav_chat_btn", "_nav_chat"),
    Feature("task", "任务", "🧭", "任务", MODES, 30, True,
            "创建、查看、继续任务", "nav_task_btn", "_nav_task"),
    Feature("resources", "资料", "📚", "资料", MODES, 40, True,
            "知识库、历史与记忆", "nav_resources_btn", "_nav_resources"),
    Feature("settings", "设置", "⚙", "常用", MODES, 50, True,
            "模型、界面、帮助和高级选项", "nav_settings_btn", "_nav_settings"),
    Feature("attach", "附件", "＋", "常用", MODES, 60, True,
            "上传文件或截图", "plus_btn", "_show_plus_menu"),
    Feature("voice", "语音输入", "🎙", "工具", MODES, 70, True,
            "语音输入 / 输入切换", "voice_btn", "_voice_btn_clicked"),
    Feature("send", "发送", "➤", "常用", MODES, 80, True,
            "发送聊天或任务", "send_btn", "send"),

    # ---------- 高级模式首屏 ----------
    Feature("module_buttons", "模块按钮", "🧩", "插件/MCP", (ADVANCED,), 110,
            False, "已安装模块自己声明的快捷按钮", "sidebar_modules_box"),
    Feature("realtime_chat", "语音对话", "🎧", "工具", (ADVANCED,), 120,
            False, "实时语音对话（实时 / 按键两种模式）", "realtime_btn", "_rt_toggle"),
    Feature("model_selector", "模型选择", "🤖", "工具", (ADVANCED,), 130,
            False, "切换本地 / 云端模型", "model_btn", "switch_model"),
    # 2026-10-22：代码编辑器 / Agent 旅程 / AI 代码 Agent 三个入口
    # 合并为「🧰 工作台」一个入口（同一窗口内：左文件树 + 右上编辑器 +
    # 右下 AI 面板）。旧的三个 action 名保留为别名，见下方 ALIASES，
    # 避免历史代码/文档/命令面板里的调用失效。
    Feature("workbench", "工作台", "🧰", "工具", (ADVANCED,), 140,
            False, "编辑器 + AI 面板同屏：改代码、让 AI 改、看 diff 都在一个窗口",
            "editor_btn", "open_workbench"),
    Feature("computer_agent", "电脑 Agent", "PC", "工具", (ADVANCED,), 147,
            False, "观察屏幕、生成跨应用计划、执行并验证",
            "computer_agent_btn", "computer_agent_dialog"),
    Feature("login", "登录", "🔑", "常用", (ADVANCED,), 150,
            False, "登录 / 切换账号", "login_btn_sb", "show_login"),
    Feature("clear_chat", "清空聊天", "🗑", "常用", (ADVANCED,), 160,
            False, "清空当前聊天", "", "clear_chat"),
    Feature("task_center", "任务中心", "🧭", "任务", MODES, 170,
            False, "统一任务页面：计划、步骤、确认、结果",
            "task_center_btn", "open_task_center"),
    Feature("security_center", "安全中心", "🛡", "安全", MODES, 180,
            False, "权限、网络、审计和安全事件",
            "security_center_btn", "security_center_dialog"),
    Feature("plugin_market", "插件市场", "🔌", "插件/MCP", MODES, 190,
            False, "安装 / 卸载 / 热加载模块", "plugin_market_btn", "plugin_dialog"),
    Feature("skills", "技能管理", "🧠", "工具", (ADVANCED,), 205,
        False, "导入/导出技能，确认/拒绝自学习", "", "open_skills_dialog"),
    Feature("mcp", "MCP", "🧷", "插件/MCP", MODES, 200,
            False, "MCP 服务器管理", "mcp_btn", "mcp_dialog"),
    Feature("memory", "记忆", "🧠", "资料", MODES, 210,
            False, "记忆时间线、图谱与编辑", "memory_btn", "memory_view_dialog"),
    Feature("logs", "日志", "📋", "开发", MODES, 220,
            False, "运行日志与错误记录", "logs_btn", "log_dialog"),
    Feature("knowledge_base", "知识库", "📚", "资料", MODES, 230,
            False, "导入和管理知识库资料", "kb_btn", "kb_dialog"),
    Feature("history", "历史记录", "🕒", "资料", MODES, 240,
            False, "搜索、导出历史聊天", "history_btn", "history_dialog"),
    Feature("command_palette", "命令面板", "⌘", "常用", MODES, 250,
            False, "Ctrl+K 搜索所有能力", "command_palette_btn", "command_palette"),
    Feature("onboarding", "首次设置向导", "🧭", "常用", MODES, 260,
            False, "模型没配好时重新配置", "onboarding_btn", "onboarding_dialog"),
    Feature("tutorial", "新手教程", "📖", "常用", MODES, 270,
            False, "三分钟学会聊天、任务和资料", "tutorial_btn", "show_tutorial"),
    Feature("system_check", "系统自检", "🧪", "开发", (ADVANCED,), 290,
            False, "深度自检、备份和训练", "system_check_btn", "sys_dialog"),
    Feature("module_map", "模块星图", "🕸", "开发", (ADVANCED,), 300,
            False, "查看模块拓扑图", "module_map_btn", "module_map_dialog"),
    Feature("feedback", "意见反馈", "💬", "常用", MODES, 310,
            False, "给开发者留言", "feedback_btn", "show_feedback"),
    Feature("update", "检查更新", "🔄", "开发", (ADVANCED,), 320,
            False, "检查新版本 / 回滚", "update_btn", "update_dialog"),
    Feature("bot", "机器人", "🤖", "插件/MCP", (ADVANCED,), 350,
            False, "企业微信 / 钉钉机器人", "bot_btn", "bot_dialog"),
    Feature("calendar", "日历待办", "📅", "工具", (ADVANCED,), 360,
            False, "日历、待办与笔记", "calendar_btn", "tools_dialog"),
    Feature("deep_research", "深度研究", "🔬", "资料", (ADVANCED,), 388,
            False, "多跳联网研究，带引用报告", "research_btn", "research_dialog"),
    Feature("web_console", "Web 控制台", "🌐", "开发", (ADVANCED,), 386,
            False, "手机/浏览器聊天与任务查看（localhost + token）", "", "open_web_console"),
    Feature("trace_view", "Trace 回看", "📊", "开发", (ADVANCED,), 389,
            False, "任务时间树回看，失败步骤标红", "", "trace_view_dialog"),
    Feature("roles", "群聊角色", "👥", "工具", (ADVANCED,), 395,
            False, "管理群聊角色人设和触发关键词", "", "roles_dialog"),
]

FEATURES: Dict[str, Feature] = {f.id: f for f in _FEATURES}

# 唯一约束在 import 时就暴露，避免后加功能时悄悄覆盖旧 id
if len(FEATURES) != len(_FEATURES):
    raise RuntimeError("FeatureRegistry 存在重复 id")

# 这些是需求中明确列出的简单模式首屏主要按钮，正好 7 个。
SIMPLE_PRIMARY_IDS = (
    "new_chat", "task", "resources", "settings", "attach", "voice", "send",
)

# 头像菜单只保留 5 类高频入口；模式切换由主窗口动态生成。
# 其余入口全部放进更多，且两个菜单之间不允许重复。
AVATAR_MENU_IDS = (
    "update", "settings", "tutorial",
)

MORE_MENU_GROUPS = (
    ("任务", (
        "task_center",
    )),
    ("资料", (
        "knowledge_base", "history", "memory",
    )),
    ("工具", (
        "model_selector", "workbench",
        "realtime_chat", "computer_agent",
    )),
    ("安全", (
        "security_center",
    )),
    ("插件/MCP", (
        "plugin_market", "mcp",
    )),
    ("开发", (
        "command_palette",
    )),
    ("帮助", (
        "onboarding",
    )),
)


# 旧 feature id -> 新 id。合并入口后，历史代码/命令面板/文档里
# 仍可能按旧名字查找，这里统一转发，避免"入口消失"。
ALIASES = {
    "code_editor": "workbench",
    "agent_journey": "workbench",
    "code_agent": "workbench",
    "voice_chat": "realtime_chat",
    "scheduled_tasks": "task_center",
}


def get_feature(feature_id: str):
    fid = ALIASES.get(feature_id, feature_id)
    return FEATURES.get(fid)


def feature_ids_for_mode(mode: str) -> Tuple[str, ...]:
    mode = SIMPLE if mode != ADVANCED else ADVANCED
    return tuple(f.id for f in FEATURES.values() if f.visible_in(mode))


def is_visible(feature_id: str, mode: str) -> bool:
    f = FEATURES.get(feature_id)
    return bool(f and f.visible_in(mode))


def primary_features(mode: str = SIMPLE) -> Tuple[Feature, ...]:
    """首屏主要按钮列表（只返回显式标记 primary 的入口）。"""
    mode = SIMPLE if mode != ADVANCED else ADVANCED
    return tuple(f for f in FEATURES.values()
                 if f.primary and f.visible_in(mode))


def primary_button_budget(mode: str = SIMPLE) -> int:
    return len(primary_features(mode))


def feature_by_label(label: str):
    for f in FEATURES.values():
        if f.label == label or f.icon + " " + f.label == label:
            return f
    return None


def command_group_for(label: str, default: str = "工具") -> str:
    f = feature_by_label(label)
    return f.group if f else default


def command_groups(features: Iterable[Feature] = None) -> Dict[str, list]:
    out = {g: [] for g in COMMAND_GROUPS}
    for f in (features if features is not None else FEATURES.values()):
        out.setdefault(f.group, []).append(f)
    for v in out.values():
        v.sort(key=lambda x: x.order)
    return out