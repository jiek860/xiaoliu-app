# -*- coding: utf-8 -*-
"""core 模块的能力声明

为什么需要这个文件
------------------
72 个登记模块里，**48 个住在 modules/installed（是插件，有签名清单条目），
另外 24 个住在 core/（不是插件，没有任何清单条目）**。
而"只能靠按钮到达"的那批功能（统计报表/记忆整理/成长报告/GPU检测…）
绝大多数正好在这 24 个里。

所以能力声明分两个来源：
    来源 A 插件模块  → 模块里声明 TOOLS → 由 rebuild 写进 manifest.tools（带签名）
    来源 B core 模块 → 本文件集中声明（它们没有清单可用）

两条来源由 core/module_caps.py 合并成一个工具表交给 tool_caller。

字段说明
--------
    mod       模块名（与 LAZY_MAP 的键一致）
    method    要调用的方法名
    name      暴露给模型的工具名（唯一，避免和内置工具撞）
    desc      给模型看的一句话说明
    args      {参数名: 说明}；**参数名必须和方法签名一致**，
              否则分发器会退回"只传第一个值"（见 tool_caller.dispatch）
    readonly  True = 只读，不会改数据
    confirm   True = 执行前弹窗确认
    danger    True = 危险操作（还受规则引擎开关约束）
    hints     关键词，给第一级粗筛用（避免把所有能力都塞进 LLM 提示词）

注意：**只声明经过实测能跑通的能力**。声明了但跑不通，
比"没有这个能力"更糟 —— 用户说一句，得到的是一个报错。
"""

CORE_CAPS = [
    # ─────────── 统计与报告（只读）───────────
    {
        "mod": "stats_report", "method": "generate", "name": "stats_report",
        "desc": "用量统计：聊了多少条、多少记忆卡、多少事件",
        "args": {"period": "统计周期天数，默认 7"},
        "readonly": True,
        "hints": ["统计", "报表", "用量", "多少条", "用了多少", "数据统计"],
    },
    {
        "mod": "growth_report", "method": "report", "name": "growth_report",
        "desc": "人格成长情况：认识多少天、关系阶段、里程碑",
        "args": {},
        "readonly": True,
        "hints": ["成长", "关系阶段", "认识多久", "认识多少天", "里程碑"],
    },
    {
        "mod": "mood_report", "method": "report", "name": "mood_report",
        "desc": "情绪统计：最近一段时间的心情分布",
        "args": {"days": "统计多少天，默认 7"},
        "readonly": True,
        "hints": ["心情", "情绪", "心情日报", "情绪统计"],
    },
    # ─────────── 记忆维护 ───────────
    {
        "mod": "memory_organizer", "method": "check_conflicts",
        "name": "memory_conflicts",
        "desc": "检查记忆卡之间有没有互相矛盾的说法",
        "args": {},
        "readonly": True,
        "hints": ["记忆冲突", "记忆矛盾", "前后矛盾", "查冲突"],
    },
    {
        "mod": "memory_organizer", "method": "auto_organize",
        "name": "memory_organize",
        "desc": "合并重复的记忆卡（会改写 memory_cards.jsonl）",
        "args": {},
        "confirm": True,
        "hints": ["整理记忆", "合并记忆", "记忆重复", "清理记忆", "记忆乱"],
    },
    {
        "mod": "memory_archiver", "method": "list_archives",
        "name": "memory_archives",
        "desc": "看已经归档了哪些旧记忆",
        "args": {},
        "readonly": True,
        "hints": ["归档列表", "归档了哪些", "旧记忆"],
    },
    {
        "mod": "memory_archiver", "method": "archive_old",
        "name": "memory_archive",
        "desc": "把 30 天前的旧记忆压缩归档",
        "args": {"days": "归档多少天前的，默认 30"},
        "confirm": True,
        "hints": ["归档记忆", "压缩记忆", "旧记忆归档"],
    },
    # ─────────── 系统信息（只读）───────────
    {
        "mod": "gpu_detector", "method": "detect", "name": "gpu_check",
        "desc": "检测这台机器有没有可用的 GPU（决定能不能跑本地大模型）",
        "args": {},
        "readonly": True,
        "hints": ["显卡", "gpu", "有没有显卡", "显存", "能跑模型吗"],
    },
    {
        "mod": "group_parallel", "method": "list_roles", "name": "group_roles",
        "desc": "列出群聊里有哪些智能体角色",
        "args": {},
        "readonly": True,
        "hints": ["群聊角色", "有哪些角色", "智能体列表"],
    },
    # ─────────── 娱乐（只读）───────────
    {
        "mod": "dream_system", "method": "get_recent_dreams", "name": "dream_recent",
        "desc": "看看它以前做过的梦",
        "args": {"count": "看几条，默认 3"},
        "readonly": True,
        "hints": ["最近的梦", "做过什么梦", "梦境记录"],
    },
    {
        "mod": "dream_system", "method": "generate_dream", "name": "dream_make",
        "desc": "让它现在做一个梦（纯娱乐）",
        "args": {},
        "hints": ["做个梦", "生成梦", "让它做梦"],
    },
    # ─────────── 导出（需要路径，但路径可以用文字给）───────────
    {
        "mod": "migration", "method": "export", "name": "migrate_export",
        "desc": "把整份数据打包成一个压缩包，换电脑时用",
        "args": {"out_path": "导出到哪个文件，如 D:\\\\x6备份.zip"},
        "hints": ["迁移", "导出数据", "打包数据", "换电脑", "备份全部"],
    },
    {
        "mod": "crash_export", "method": "export", "name": "crash_export",
        "desc": "打包日志+配置+系统信息（密钥自动脱敏），用来排查崩溃",
        "args": {"out_path": "导出到哪个文件，如 D:\\\\崩溃日志.zip"},
        "hints": ["崩溃日志", "导出日志", "报错打包", "排查"],
    },
    # ─────────── 数据清理（危险，需确认）───────────
    {
        "mod": "data_cleaner", "method": "clean_all", "name": "clean_data",
        "desc": "删掉完全重复的聊天记录 + 合并重复记忆（会改数据！）",
        "args": {},
        "confirm": True,
        "hints": ["清理数据", "去重", "删除重复", "数据清洗"],
    },
    # ─────────── 多智能体 ───────────
    {
        "mod": "group_debate", "method": "debate", "name": "debate",
        "desc": "让几个智能体就某个话题辩论",
        "args": {"topic": "辩题", "rounds": "辩几轮，默认 2"},
        "hints": ["辩论", "让它们讨论", "多智能体讨论"],
    },
    {
        "mod": "model_vote", "method": "chat_vote", "name": "model_vote",
        "desc": "多个模型各自回答同一个问题，再投票选最好的",
        "args": {"message": "要问的问题"},
        "hints": ["投票", "多个模型", "模型对比"],
    },
]

# 只能靠 UI 完成的（密码不能打进聊天 —— 会进日志）
UI_ONLY = [
    {"mod": "memory_crypto", "method": "export_encrypted",
     "why": "需要密码，密码打进聊天会留在会话记录里"},
]


def by_name():
    """返回 {工具名: 声明}，方便测试与查重"""
    return {c["name"]: c for c in CORE_CAPS}
