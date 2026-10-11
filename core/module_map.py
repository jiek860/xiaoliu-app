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
    "learning_loop": "闭环", "memory_loop": "闭环", "task_loop": "闭环", "skill_distill": "闭环",
    "smart_router": "智能体",
    "deep_search": "工具", "tool_caller": "工具", "computer_controller": "工具",
    "code_runner": "工具", "file_upload": "工具", "multimodal": "工具", "voice": "工具",
    "mcp_server": "工具",
    "task_planner": "高级", "error_lib": "高级", "auto_updater": "高级",
    "active_learning": "高级", "knowledge_qa": "高级", "reasoning_engine": "高级",
    "plugin_market": "高级", "skill_capture": "高级",
    "self_reflect": "L模块", "empathy": "L模块", "personality": "L模块",
    "forgetting_curve": "L模块", "anomaly_detector": "L模块", "memory_cards": "L模块",
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
    """扫 modules/installed/*.py 里的 trunk.call("模块","方法")，得到真实的调用边"""
    import ast
    inst = os.path.join(trunk.base, "modules", "installed")
    if not os.path.isdir(inst):
        return []
    # 文件名 -> 模块键
    f2m = {}
    for k, v in trunk._lazy.items():
        if isinstance(v, (list, tuple)) and v:
            f2m[v[0] + ".py"] = k

    edges = {}
    for fn in sorted(os.listdir(inst)):
        if not fn.endswith(".py"):
            continue
        src = f2m.get(fn)
        if not src:
            continue
        try:
            tree = ast.parse(open(os.path.join(inst, fn),
                                  encoding="utf-8", errors="ignore").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "call" and len(node.args) >= 2):
                continue
            a0, a1 = node.args[0], node.args[1]
            if not (isinstance(a0, ast.Constant) and isinstance(a1, ast.Constant)):
                continue
            tgt, meth = a0.value, a1.value
            # "__no__" 是懒加载探针惯用法（故意写错方法名只为触发加载），不算调用
            if meth == "__no__" or tgt == src or tgt not in valid or src not in valid:
                continue
            edges.setdefault((src, tgt), set()).add(meth)
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
