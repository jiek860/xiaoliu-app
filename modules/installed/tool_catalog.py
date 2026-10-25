# -*- coding: utf-8 -*-
"""内置工具清单（从 tool_caller.py 原样搬出）。

只搬数据不改行为：键、说明、参数、风控字段与原来逐项一致。
"""

BUILTIN_TOOLS = {
    "deep_search": {
        "desc": "联网搜索网页",
        "mod": "deep_search", "method": "search",
        "args": {"query": "搜索关键词"},
        "readonly": True, "risk": "network",
    },
    "vector_search": {
        "desc": "搜索历史记忆",
        "mod": "vector_store", "method": "search",
        "args": {"query": "搜索词"},
        "readonly": True, "risk": "read",
    },
    "graph_query": {
        "desc": "查询知识图谱",
        "mod": "knowledge_graph", "method": "rag_query",
        "args": {"query": "查询内容"},
        "readonly": True, "risk": "read",
    },
    "code_run": {
        "desc": "运行Python代码",
        "mod": "code_runner", "method": "run",
        "args": {"code": "Python代码"},
        "confirm": True, "danger": True,
        "danger_rule": "工具.允许代码执行", "risk": "exec",
    },
    "file_read": {
        "desc": "读文件内容",
        "mod": "file_upload", "method": "read",
        "args": {"path": "文件路径"},
        "confirm": True, "risk": "read_sensitive",
    },
    "task_plan": {
        "desc": "规划任务步骤",
        "mod": "task_planner", "method": "run_goal",
        "args": {"goal": "任务目标"},
        "readonly": True, "risk": "read",
    },
    "computer": {
        "desc": "控制电脑：打开软件/截屏/系统信息",
        "mod": "computer_controller", "method": "try_handle",
        "args": {"action": "操作"},
        "confirm": True, "risk": "ui_control",
    },
    # 浏览器（Playwright，DOM 选择器级，headless）。
    # 入口是 browser.run/1 个文本参数 —— 注意 tool_caller 分发时只传
    # list(args.values())[0]，多参数传不过去，所以这里只声明 1 个参数，
    # 由 browser.try_handle 自己解析（和上面的 computer 同一形状）。
    "browser": {
        "desc": "浏览器：打开网页/读页面文字/点击/输入/截图（DOM级）",
        "mod": "browser", "method": "run",
        "args": {"action": "如：打开 https://example.com 并读取页面文字"},
        "confirm": True, "risk": "ui_network",
    },
    # 开发者文件工具。同样只声明 1 个参数（tool_caller 只传第一个），
    # fs_edit 的参数是一段 JSON 文本。
    "fs_read": {
        "desc": "读文件内容（带行号）",
        "mod": "computer_controller", "method": "read_text",
        "args": {"path": "文件路径"},
        "confirm": True, "risk": "read_sensitive",
    },
    "fs_search": {
        "desc": "在项目目录里搜文件内容",
        "mod": "computer_controller", "method": "search_text",
        "args": {"keyword": "关键词或正则"},
        "readonly": True, "risk": "read",
    },
    "fs_edit": {
        "desc": "精确替换文件内容（原文须唯一，改前自动备份）",
        "mod": "computer_controller", "method": "edit_text",
        "args": {"spec": 'JSON: {"path":"a.py","old":"原文","new":"新文"}'},
        "confirm": True, "danger": True,
        "danger_rule": "工具.允许文件修改", "risk": "write",
    },
    # UI 元素树：按控件名操作，不依赖坐标（需 uiautomation）
    "ui_find": {
        "desc": "按控件名/类型在窗口里找控件（只定位，不点击）",
        "mod": "computer_controller", "method": "ui_find",
        "args": {"name": "控件名，如：确定"},
        "readonly": True, "risk": "read",
    },
    "ui_click": {
        "desc": "按控件名点击按钮/链接（比点坐标可靠）",
        "mod": "computer_controller", "method": "ui_click",
        "args": {"name": "控件名，如：确定"},
        "confirm": True, "risk": "ui_control",
    },
    "ui_dump": {
        "desc": "打印某窗口的控件树，用于看清程序界面结构",
        "mod": "computer_controller", "method": "ui_dump",
        "args": {"window": "窗口名，如：记事本"},
        "readonly": True, "risk": "read",
    },
    # 命令执行：默认关闭（规则「电脑控制.允许命令」= false），
    # 开启后也只放白名单命令且每条要弹窗确认。列在这里是为了
    # 开启后 LLM 能调用它 —— 防线是"规则 + 确认"，不是把它藏起来。
    "shell": {
        "desc": "执行一条白名单内的命令（默认禁用，需规则开启）",
        "mod": "computer_controller", "method": "shell",
        "args": {"cmd": "如：git status（不允许 && | > 等串联）"},
        "confirm": True, "danger": True,
        "danger_rule": "电脑控制.允许命令", "risk": "exec",
    },
}
