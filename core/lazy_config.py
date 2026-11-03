# -*- coding: utf-8 -*-
"""懒加载配置 v3.0 - 全部使用英文模块名，中文仅在 display 字段保留"""

# (英文文件名, 类名, 中文显示名)
LAZY_MAP = {
    # ===== 对话核心 =====
    "personality":      ("personality",      "PersonalityEngine",   "人格引擎"),
    "memory_cards":     ("memory_cards",     "MemoryCards",         "记忆卡"),
    "memory_loop":      ("memory_loop",      "MemoryPipeline",      "记忆闭环"),
    # ===== 记忆系统 =====
    "forgetting_curve": ("forgetting_curve", "ForgettingCurve",     "遗忘曲线"),
    # ===== 搜索 =====
    "deep_search":      ("deep_search",      "DeepSearch",          "深度搜索"),
    "deep_research":    ("deep_research",    "DeepResearch",        "深度研究"),
    # ===== 电脑控制 =====
    "computer_controller": ("computer_controller", "ComputerController", "电脑控制"),
    # ===== 语音 =====
    "stt":              ("voice",            "Voice",               "语音识别"),
    "tts":              ("tts",              "TTS",                 "文字转语音"),
    "voice":            ("voice",            "Voice",               "语音模块"),
    # ===== 多模态 =====
    "multimodal":       ("multimodal",       "Multimodal",          "多模态"),
    "image_ocr":        ("image_ocr",        "OCR",                 "图片识别"),
    # ===== 群聊 =====
    "group_chat":       ("group_chat",       "GroupChat",           "群聊"),
    "group_parallel":   ("group_parallel",   "GroupChatParallel",   "群聊并行"),
    "group_loop":       ("group_loop",       "GroupChatPipeline",   "群聊闭环"),
    # ===== 闭环 =====
    "learning_loop":    ("learning_loop",    "LearningPipeline",    "学习闭环"),
    "task_loop":        ("task_loop",        "TaskPipeline",        "任务闭环"),
    "skill_capture":    ("skill_capture",    "SkillCapture",        "技能捕获"),
    # ===== 智能体 =====
    "smart_router":     ("smart_router",     "SmartRouter",         "智能路由"),
    "tool_caller":      ("tool_caller",      "ToolCaller",          "工具调用"),
    "task_planner":     ("task_planner",     "TaskPlanner",         "任务规划"),
    # ===== 工具 =====
    "code_runner":      ("code_runner",      "CodeExecutor",        "代码执行"),
    "file_upload":      ("file_upload",      "FileUpload",          "文件上传"),
    "browser":          ("browser",          "Browser",             "浏览器操作"),
    "translate":        ("translate",        "Translator",          "翻译"),
    # ===== 高级 =====
    "auto_updater":     ("auto_updater",     "AutoUpdater",         "自动更新"),
    "plugin_market":    ("plugin_market",    "PluginMarket",        "插件市场"),
    "mcp_client":       ("mcp_client",       "MCPClient",           "MCP客户端"),
    "mcp_server":       ("mcp_server",       "MCPServer",           "MCP服务"),
    "coder_pro":        ("coder_pro",        "CoderPro",            "代码专家"),
    "workflow_runner":  ("workflow_runner", "WorkflowRunner",      "工作流"),
    "web_agent":        ("web_agent",       "WebAgent",            "网页智能体"),
    "api_server":       ("api_server",      "ApiServer",           "HTTP API"),
    "graph_rag":        ("graph_rag",       "GraphRAG",            "知识图谱摘要"),
    # ===== L 模块 =====
    "self_reflect":     ("self_reflect",     "ReflectEngine",       "自我反思"),
    "anomaly_detector": ("anomaly_detector", "AnomalyDetector",     "异常检测"),
    # ===== 后台 =====
    "scheduler":        ("scheduler",        "Scheduler",           "定时任务"),
    "hot_reload":       ("hot_reload",       "HotReload",           "热重载"),
    # ===== 其他 =====
    "error_lib":        ("error_lib",        "ErrorLibrary",        "错误库"),
    "knowledge_qa":     ("knowledge_qa",     "KnowledgeQnA",        "知识问答"),
    # ===== 智能体占位 =====
    "agent_coder":      ("agent_coder",      "AgentCoder",          "编程小匠"),
    "agent_analyst":    ("agent_analyst",    "AgentAnalyst",        "分析专家"),
    "agent_planner":    ("agent_planner",    "AgentPlanner",        "策划专家"),

    # ===== v25新增模块 =====
    "crash_export":     ("crash_export",     "CrashExport",         "崩溃日志导出"),
    "migration":        ("migration",       "Migration",           "一键迁移"),
    "sensitive_detector": ("sensitive_detector", "SensitiveDetector", "敏感信息检测"),
    "cache":            ("cache",            "DiskCache",           "磁盘缓存"),
    "realtime_chat":         ("realtime_chat",       "RealtimeChat",         "实时对话"),
    "mood_report":      ("mood_report",      "MoodReport",          "心情日报"),
    "growth_report":    ("growth_report",    "GrowthReport",        "成长报告"),
    "action_recorder":  ("action_recorder",  "ActionRecorder",      "操作录制"),
    "tool_call_logger": ("tool_call_logger", "ToolCallLogger",      "工具调用日志"),
    "agent_flow":       ("agent_flow",       "AgentFlow",           "智能体流程"),
    "local_fallback":   ("local_fallback",   "LocalFallback",       "本地兜底"),
    "personality_market": ("personality_market", "PersonalityMarket", "人格市场"),
    "dream_system":     ("dream_system",     "DreamSystem",         "梦境系统"),
    "memory_archiver":  ("memory_archiver",  "MemoryArchiver",      "记忆归档"),
    "plugin_signer":    ("plugin_signer",    "PluginSigner",        "插件签名"),
    "gpu_detector":     ("gpu_detector",     "GPUDetector",         "GPU检测"),

    # ===== v26新增模块 =====
    "model_vote":       ("model_vote",       "ModelVote",           "多模型投票"),
    "group_debate":     ("group_debate",     "GroupDebate",         "多智能体辩论"),
    "memory_organizer": ("memory_organizer", "MemoryOrganizer",     "记忆自动整理"),
    "memory_crypto":    ("memory_crypto",    "MemoryCrypto",        "记忆加密"),
    "memory_optimizer": ("memory_optimizer",  "MemoryOptimizer",     "内存优化"),
    "startup_optimizer": ("startup_optimizer", "StartupOptimizer", "启动优化"),
    "data_cleaner":     ("data_cleaner",     "DataCleaner",         "数据清洗"),
    "stats_report":     ("stats_report",     "StatsReport",         "统计报表"),
    "browser_session":  ("browser_session",  "BrowserSession",      "浏览器会话"),
    # 补登记：工具类模块
    "weather":          ("weather",          "Weather",             "天气查询"),
    "notes":            ("notes",            "Notes",               "笔记工具"),
    "todo":             ("todo",             "Todo",                "待办清单"),
    "calendar":         ("calendar",         "Calendar",            "日历事件"),
}


# ===== 来源登记（2026-11-02，B0）=====
# 一个 LAZY_MAP 条目到底属于「插件市场插件」还是「core 内置模块」，
# 以前只能靠「modules/installed/<file>.py 是否存在」去猜 —— 猜错会带来两个误导：
#   ① 插件市场的安装/卸载/签名流程对 core 模块无效；
#   ② core 模块文件丢了，日志只说「模块未安装，请到插件市场下载」，把人指错方向。
# 现在显式登记来源，_load_lazy 按来源只查对应目录，不再双路径乱猜。
CORE_ONLY_KEYS = frozenset({
    "crash_export", "migration", "sensitive_detector",
    "mood_report", "growth_report", "action_recorder", "tool_call_logger",
    "agent_flow", "local_fallback", "personality_market", "dream_system",
    "memory_archiver", "plugin_signer", "gpu_detector",
    "model_vote", "group_debate", "browser_session", "memory_organizer",
    "memory_crypto", "memory_optimizer", "startup_optimizer",
    "data_cleaner", "stats_report",
})

# 同一文件对应多个 key 的语义别名（允许，不是重复登记）：
#   stt（语音识别）/ voice（语音模块）共用 voice.py；
#   module_map 用 stt 做分组说明，check_modules/check_shapes 也把它俩一并跳过。
SAME_FILE_ALIASES = {"stt": "voice"}


def source_of(key):
    """返回模块的真实来源：'core'（内核内置）或 'installed'（插件市场）"""
    return "core" if key in CORE_ONLY_KEYS else "installed"


def modules_by_source(src):
    """按来源筛出登记条目，便于调试与守卫核对"""
    return {k: v for k, v in LAZY_MAP.items() if source_of(k) == src}


LAZY_CORE = modules_by_source("core")
LAZY_PLUGIN = modules_by_source("installed")
