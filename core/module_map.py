# -*- coding: utf-8 -*-
"""模块星图导出 —— 把 trunk 的模块拓扑画成 data/modules_map.js

从 core/trunk.py 搬出来的。它纯粹是「展示」，不是内核职责：
内核该管注册/懒加载/分发/生命周期，画图这种活不该占着微核的篇幅。
页面在 docs/模块星图.html（随程序入库），读的正是这里生成的 js。
"""
import json
import os

# 分组：决定星图上节点的颜色
GROUPS = {
    "trunk": "核心", "llm": "核心", "vector_store": "核心", "knowledge_graph": "核心",
    "rules_engine": "核心", "auth": "核心", "backup": "核心",
    "scheduler": "后台", "hot_reload": "后台", "mobile_remote": "后台",
    "startup_optimizer": "后台",
    "learning_loop": "闭环", "memory_loop": "闭环", "task_loop": "闭环", "skill_distill": "闭环",
    "agent_flow": "智能体",
    "smart_router": "智能体", "group_chat": "智能体", "group_parallel": "智能体",
    "group_loop": "智能体", "group_debate": "智能体", "model_vote": "智能体",
    "agent_coder": "智能体", "agent_analyst": "智能体", "agent_planner": "智能体",
    "deep_search": "工具", "tool_caller": "工具", "computer_controller": "工具",
    "code_runner": "工具", "file_upload": "工具", "multimodal": "工具", "voice": "工具",
    "mcp_server": "工具", "mcp_client": "工具", "stt": "工具", "tts": "工具",
    "image_ocr": "工具", "browser": "工具", "browser_session": "工具",
    "translate": "工具", "weather": "工具", "notes": "工具", "todo": "工具",
    "calendar": "工具", "cache": "工具", "realtime_chat": "工具",
    "task_planner": "高级", "error_lib": "高级", "auto_updater": "高级",
    "active_learning": "高级", "knowledge_qa": "高级", "reasoning_engine": "高级",
    "plugin_market": "高级", "skill_capture": "高级", "crash_export": "高级",
    "migration": "高级", "sensitive_detector": "高级", "action_recorder": "高级",
    "tool_call_logger": "高级", "local_fallback": "高级", "personality_market": "高级",
    "plugin_signer": "高级", "graph_db": "高级", "gpu_detector": "高级",
    "data_cleaner": "高级", "stats_report": "高级", "mood_report": "高级",
    "growth_report": "高级",
    # 记忆：原来这批全落在"其他"（画成灰点），单独成组才看得懂
    "memory_cards": "记忆", "forgetting_curve": "记忆", "memory_archiver": "记忆",
    "memory_organizer": "记忆", "memory_crypto": "记忆", "memory_optimizer": "记忆",
    "dream_system": "记忆",
    "self_reflect": "L模块", "empathy": "L模块", "personality": "L模块",
    "anomaly_detector": "L模块",
}

# 鼠标悬停时的说明
DESCS = {
    "trunk": "微核躯干：注册/总线", "llm": "大模型：本地+云端+流式",
    "vector_store": "向量检索：nomic-embed+余弦", "knowledge_graph": "知识图谱：三元组+多跳",
    "rules_engine": "规则引擎：底层规则", "auth": "账号激活登录：激活码授权",
    "backup": "自动备份：保留2份", "scheduler": "定时任务：24h后台",
    "hot_reload": "热更新：沙盒+回滚", "mobile_remote": "手机远程",
    "learning_loop": "学习闭环：找缺口→搜索→入库", "memory_loop": "记忆闭环：对话→记忆卡→复习",
    "task_loop": "任务闭环：拆步→执行→验证", "skill_distill": "技能沉淀：成功任务→SKILL",
    "smart_router": "智能路由：LLM判断谁答", "deep_search": "深度搜索：多源并行",
    "tool_caller": "工具调用：LLM自动决定", "computer_controller": "电脑控制：鼠标键盘",
    "code_runner": "代码沙盒：隔离跑Python", "file_upload": "文件上传：PDF/Word",
    "multimodal": "多模态：看图/听音频", "voice": "语音：STT/TTS",
    "mcp_server": "MCP服务：连外部工具", "task_planner": "任务规划：自动拆步",
    "error_lib": "错误库：记录+修复建议", "auto_updater": "自动更新：自更新流水线",
    "active_learning": "主动学习：定时上网找知识", "knowledge_qa": "RAG：检索增强生成",
    "reasoning_engine": "推理引擎：多跳推理", "plugin_market": "插件市场：一键装模块",
    "skill_capture": "技能捕获：自动沉淀", "self_reflect": "自我反思：回答后打分",
    "empathy": "共情：情绪感知", "personality": "人格引擎：小6性格",
    "forgetting_curve": "遗忘：旧记忆自动删", "anomaly_detector": "异常检测：行为偏差",
    "memory_cards": "记忆卡：情景记忆",
    # ---- 补齐的 42 个（原来 tooltip 是空的）----
    "stt": "语音识别：说话转文字", "tts": "文字转语音：朗读回复",
    "image_ocr": "图片识别：提取图中文字", "browser": "浏览器操作：打开/点击/填表",
    "browser_session": "浏览器会话：cookie 持久化", "translate": "翻译：中英互译",
    "mcp_client": "MCP客户端：接外部工具服务", "group_chat": "群聊：多角色一起答",
    "group_parallel": "群聊并行：多角色同时答", "group_loop": "群聊闭环：讨论→汇总",
    "group_debate": "多智能体辩论：互相挑错", "model_vote": "多模型投票：少数服从多数",
    "agent_coder": "编程小匠：写代码的智能体", "agent_analyst": "分析专家：拆解问题",
    "agent_planner": "策划专家：出方案", "agent_flow": "智能体流程：记录执行步骤",
    "crash_export": "崩溃日志导出：打包给开发者", "migration": "一键迁移：换电脑搬数据",
    "sensitive_detector": "敏感信息检测：拦隐私外泄", "cache": "磁盘缓存：同问题不重复问模型",
    "realtime_chat": "实时对话：语音连续聊、可打断", "mood_report": "心情日报：今天情绪小结",
    "growth_report": "成长报告：陪你的时间线", "action_recorder": "操作录制：回放做过的事",
    "tool_call_logger": "工具调用日志：谁调了什么", "local_fallback": "本地兜底：模型挂了也能回话",
    "personality_market": "人格市场：换人格包", "dream_system": "梦境系统：离线时做梦",
    "memory_archiver": "记忆归档：旧记忆打包存放", "plugin_signer": "插件签名：验签防篡改",
    "graph_db": "知识图谱存储：SQLite 版三元组", "gpu_detector": "GPU检测：看看能不能跑本地模型",
    "memory_organizer": "记忆自动整理：合并重复、去冲突", "memory_crypto": "记忆加密：本地加密存储",
    "memory_optimizer": "内存优化：空闲时回收", "startup_optimizer": "启动优化：预热与延迟加载",
    "data_cleaner": "数据清洗：清无效记录", "stats_report": "统计报表：用量与数据统计",
    "weather": "天气查询：问天气时联网取", "notes": "笔记工具：随手记",
    "todo": "待办清单：待办增删改", "calendar": "日历事件：日程提醒",
}

# 节点上显示的短名
CNS = {
    "trunk": "微核躯干", "llm": "大模型", "vector_store": "向量检索",
    "knowledge_graph": "知识图谱", "rules_engine": "规则引擎", "auth": "账号授权",
    "backup": "自动备份", "scheduler": "定时任务", "hot_reload": "热更新",
    "mobile_remote": "手机远程", "learning_loop": "学习闭环", "memory_loop": "记忆闭环",
    "task_loop": "任务闭环", "skill_distill": "技能沉淀", "smart_router": "智能路由",
    "deep_search": "深度搜索", "tool_caller": "工具调用", "computer_controller": "电脑控制",
    "code_runner": "代码沙盒", "file_upload": "文件上传", "multimodal": "多模态",
    "voice": "语音", "mcp_server": "MCP服务", "task_planner": "任务规划",
    "error_lib": "错误库", "auto_updater": "自动更新", "active_learning": "主动学习",
    "knowledge_qa": "RAG引擎", "reasoning_engine": "推理引擎", "plugin_market": "插件市场",
    "skill_capture": "技能捕获", "self_reflect": "自我反思", "empathy": "共情",
    "personality": "人格引擎", "forgetting_curve": "遗忘", "anomaly_detector": "异常检测",
    "memory_cards": "记忆卡",
}

# 关键闭环连接（跨组）。改模块名时记得同步，虽然下面有 _valid 兜底。
LOOP_LINKS = [
    ["learning_loop", "active_learning"], ["task_loop", "task_planner"],
    ["knowledge_qa", "vector_store"], ["knowledge_qa", "knowledge_graph"],
    ["knowledge_qa", "deep_search"], ["skill_distill", "skill_capture"],
    ["memory_loop", "memory_cards"], ["memory_loop", "forgetting_curve"],
    ["self_reflect", "personality"], ["empathy", "personality"],
    ["computer_controller", "code_runner"], ["file_upload", "knowledge_qa"],
    ["multimodal", "llm"], ["voice", "llm"], ["tool_caller", "deep_search"],
]


def build(trunk):
    """算出 {modules, links}，不落盘"""
    # trunk 必须自己也是一个节点：它是星心。原来节点表只有模块，"trunk" 不在其中，
    # 而查看器（ECharts）的 links 端点不存在会被静默丢弃 —— 结果所有星型连线
    # 一条都画不出来，可这张图的卖点就是星型拓扑。
    #
    # 中文名兜底：CNS 只覆盖 30 多个名字，其余模块原来直接显示英文 key
    # （stt / weather / memory_crypto…）。LAZY_MAP 每条本来就带第 3 个字段就是
    # 中文显示名，拿它兜底，不用再维护第二份对照表。
    _cn_of_lazy = {k: v[2] for k, v in trunk._lazy.items() if len(v) >= 3 and v[2]}
    all_names = (["trunk"] + list(trunk.modules.keys())
                 + [k for k in trunk._lazy.keys() if k not in trunk.modules])

    modules = [{
        "name": n,
        "cn": (CNS.get(n) or _cn_of_lazy.get(n) or n),
        "desc": DESCS.get(n, ""),
        "group": GROUPS.get(n, "其他"),
        "loaded": (n == "trunk" or n in trunk.modules),
    } for n in all_names]

    # 星型：所有模块都连 trunk
    links = [[n, "trunk"] for n in all_names if n != "trunk"]

    # 防御：任一端点不存在就丢掉。以后再改名也画不出悬空边。
    _valid = set(all_names)
    links.extend([e for e in LOOP_LINKS if e[0] in _valid and e[1] in _valid])

    # 去重（LOOP_LINKS 内部偶尔会撞）
    _seen, _uniq = set(), []
    for a, b in links:
        k = (a, b) if a <= b else (b, a)
        if k in _seen:
            continue
        _seen.add(k)
        _uniq.append([a, b])

    # 真实的模块间调用（都经 trunk.call 转接，模块之间没有直接 import）。
    # 注意：这里原来是「组内互联」—— 同组节点两两连线，42 个"其他"组模块
    # 就画出 C(42,2)=861 条边，占了全图 91%，看上去像模块互相乱接。
    # 那只是分组着色的一种画法，不是程序里的连线，会严重误导人（实测真实
    # 跨模块调用只有 9 条）。所以改成只画"真的会互相调用"的边。
    calls = _real_calls(trunk, _valid)
    return {"modules": modules, "links": _uniq, "calls": calls}


def _real_calls(trunk, valid):
    """扫出真实的模块间调用边。

    为什么不能只认 trunk.call("字面量", "字面量")
    --------------------------------------------
    原来只认这一种形态，结果一批**正在跑**的模块在星图上看不到任何调用者，
    看起来像孤儿（实测被误判过的：agent_coder / agent_analyst / agent_planner /
    empathy / plugin_signer / stt）。静态扫不到，人就会以为坏了或者没用了。

    现在承认五种形态：
        ① 字面量       trunk.call("mod", "meth")
        ② 映射表驱动    AGENTS = {"代码": "agent_coder"}; trunk.call(AGENTS[k], "meth")
        ③ 直接 import   from core.plugin_signer import PluginSigner
        ④ 别名          stt / voice 指向同一个文件 -> 两个键都要记边，
                        否则 code 里用 "voice"、图上看 "stt" 就成了孤儿
        ⑤ 注册表驱动    tool_caller 按能力声明里的 mod 调用（声明本身就是一条边）
    """
    import ast
    inst = os.path.join(trunk.base, "modules", "installed")
    if not os.path.isdir(inst):
        return []

    # 文件 -> 所有指向它的模块键（处理别名：voice.py 同时被 stt 和 voice 指向）
    f2keys = {}
    for k, v in trunk._lazy.items():
        if isinstance(v, (list, tuple)) and v:
            f2keys.setdefault(v[0] + ".py", []).append(k)

    # 模块键 -> 该键对应的文件（用来把 "voice" 的调用也算到 "stt" 头上）
    def same_file_keys(name):
        for fn, ks in f2keys.items():
            if name in ks:
                return ks
        return [name]

    def table_strings(tree):
        """文件里"字典/列表字面量"中的模块名集合（映射表驱动的调用目标）"""
        out = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            val = getattr(node, "value", None)
            if not isinstance(val, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
                continue
            for sub in ast.walk(val):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    if sub.value in valid:
                        out.add(sub.value)
        return out

    def import_targets(tree):
        """直接 import 的模块（绕过 trunk.call 的那条路）"""
        out = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            parts = node.module.split(".")
            # from core.X import ...            -> X
            # from modules.installed.X import .. -> X
            if len(parts) >= 2 and parts[0] in ("core", "modules"):
                cand = parts[-1]
                if cand in valid:
                    out.add(cand)
        return out

    edges = {}
    for fn in sorted(os.listdir(inst)):
        if not fn.endswith(".py"):
            continue
        src_keys = f2keys.get(fn)
        if not src_keys:
            continue
        src = src_keys[0]
        if src not in valid:
            continue
        try:
            tree = ast.parse(open(os.path.join(inst, fn),
                                  encoding="utf-8", errors="ignore").read())
        except Exception:
            continue

        tstr = table_strings(tree)
        targets = {}          # 目标模块键 -> 方法名集合

        def add(tgt, meth):
            if not tgt or tgt in src_keys or tgt not in valid:
                return
            # 别名：同一个文件的其它键也记上，免得图上显示成孤儿
            for k in same_file_keys(tgt):
                if k in valid and k not in src_keys:
                    targets.setdefault(k, set()).add(meth)

        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "call" and len(node.args) >= 2):
                a0, a1 = node.args[0], node.args[1]
                meth = (a1.value if isinstance(a1, ast.Constant)
                        and isinstance(a1.value, str) else None)
                # "__no__" 是懒加载探针惯用法（故意写错方法名只为触发加载）
                if meth == "__no__":
                    continue
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    add(a0.value, meth or "按变量分发")        # ① 字面量
                else:
                    # ② 表驱动：目标就是本文件表里的那些模块名。
                    #    方法名也可能是变量（如 tool_caller 的 info["method"]）——
                    #    以前标成 "?"，图上完全看不出是怎么调的；
                    #    现在标"按表分发"，至少说明"目标来自本文件的表"。
                    for t in tstr:
                        add(t, meth or "按表分发")

        for t in import_targets(tree):                        # ③ 直接 import
            add(t, "直接 import")

        for tgt, ms in targets.items():
            edges.setdefault((src, tgt), set()).update(ms)

    # ⑤ 注册表驱动：tool_caller 按能力声明里的 mod 分发，声明本身就是调用边
    try:
        from core import module_caps
        reg = module_caps.load_tools(getattr(trunk, "base", None))
        for name, info in reg.items():
            m = info.get("mod")
            if not m or m not in valid or m == "tool_caller":
                continue
            for k in same_file_keys(m):
                if k in valid and k != "tool_caller":
                    edges.setdefault(("tool_caller", k),
                                     set()).add("按能力声明: " + name)
    except Exception:
        pass

    return [[s, t, ", ".join(sorted(ms))] for (s, t), ms in sorted(edges.items())]


def export(trunk, path=None):
    """算好并写到 data/modules_map.js，返回写入路径"""
    out = build(trunk)
    p = path or os.path.join(trunk.base, "data", "modules_map.js")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("var MODULE_DATA = "
                + json.dumps(out, ensure_ascii=False, indent=2) + ";")
    return p
