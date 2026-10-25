# -*- coding: utf-8 -*-
"""代码 Agent 的计划生成与审批门控。

为什么单独一层
--------------
复杂目标直接让模型出 patch，用户只能在 diff 弹窗里"事后"决定要不要，
而且往往已经花了多轮探索。这里在动手前先要一份结构化计划：
    步骤 / 每步目的 / 涉及文件 / 风险等级 / 要跑的测试
用户确认后才进入原有的 patch 审批与落盘流程；拒绝则零改动退出。

设计约束：
* 简单目标不打扰用户（长度、复杂关键词、候选文件数三重启发式）；
* 计划生成失败不能阻断任务，降级为启发式计划；
* 只有调用方显式传入 plan_cb 才启用，直接使用 CodeAgent 的旧代码不受影响。
"""
from __future__ import annotations

import os

from core.diagnostics import swallowed as _x6_swallowed


_PLAN_HINTS = (
    "重构", "实现", "新增", "迁移", "架构", "模块", "测试", "修复",
    "优化", "接口", "并发", "多个", "批量", "数据库", "性能", "安全",
)

_RISK_LABELS = {"low": "低", "medium": "中", "high": "高"}

PLAN_SYSTEM = (
    "你是代码任务规划 Agent。现在只做计划，不要修改任何文件。\n"
    "只输出严格 JSON，不要 Markdown：\n"
    "{\"summary\":\"一句话目标\","
    "\"steps\":[{\"title\":\"步骤\",\"purpose\":\"目的\","
    "\"files\":[\"相对路径\"],\"risk\":\"low|medium|high\"}],"
    "\"risks\":[\"风险提示\"],\"tests\":[\"要运行的测试命令\"]}\n"
    "规则：步骤 2~6 个，按依赖顺序；不知道文件就留空数组；"
    "风险等级按改动影响面评估；不要输出多余文字。"
)


def _config_section(trunk):
    cfg = getattr(trunk, "config", None) or {}
    if not isinstance(cfg, dict):
        return {}
    section = cfg.get("code_agent")
    return section if isinstance(section, dict) else {}


def plan_enabled(trunk):
    """计划审批开关：环境变量优先，其次配置，默认开启。"""
    env = str(os.environ.get("X6_CODE_AGENT_PLAN", "")).lower()
    if env in ("0", "false", "off", "no"):
        return False
    return bool(_config_section(trunk).get("plan_approval", True))


def needs_plan(goal, context_files=None):
    """启发式判断是否值得先出计划。宁可少打扰，也不要漏掉复杂任务。"""
    text = str(goal or "").strip()
    if len(text) >= 40:
        return True
    if any(h in text for h in _PLAN_HINTS):
        return True
    return len(list(context_files or [])) >= 5


def heuristic_plan(goal, context_files=None):
    files = [str(x) for x in (context_files or [])][:8]
    return {
        "summary": (str(goal or "").strip() or "执行代码任务")[:200],
        "steps": [
            {"title": "定位相关代码", "purpose": "确认要改的文件、符号与现有测试",
             "files": files, "risk": "low"},
            {"title": "应用最小修改", "purpose": "按目标改动代码，保持改动面最小",
             "files": files, "risk": "medium"},
            {"title": "运行测试与 lint", "purpose": "验证改动，失败则回修或回滚",
             "files": [], "risk": "low"},
        ],
        "risks": ["改动可能与现有实现冲突；已提供回滚清单"],
        "tests": [],
        "fallback": True,
    }


def _as_list(value, limit=10):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text[:300])
        if len(out) >= limit:
            break
    return out


def normalize_plan(data, goal, context_files=None):
    """把模型返回的计划收敛成稳定结构；不合法时回退启发式计划。"""
    if not isinstance(data, dict):
        return heuristic_plan(goal, context_files)
    if isinstance(data.get("plan"), dict):
        data = data["plan"]
    steps = []
    raw_steps = data.get("steps")
    if isinstance(raw_steps, list):
        for item in raw_steps[:8]:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("step") or "").strip()
                if not title:
                    continue
                steps.append({
                    "title": title[:120],
                    "purpose": str(item.get("purpose") or item.get("reason")
                                   or "")[:300],
                    "files": _as_list(item.get("files"), 10),
                    "risk": str(item.get("risk") or "medium").lower()[:10],
                })
            elif isinstance(item, str) and item.strip():
                steps.append({"title": item.strip()[:120], "purpose": "",
                              "files": [], "risk": "medium"})
    if not steps:
        return heuristic_plan(goal, context_files)
    summary = str(data.get("summary") or goal or "")[:300]
    return {
        "summary": summary,
        "steps": steps,
        "risks": _as_list(data.get("risks"), 8),
        "tests": _as_list(data.get("tests"), 8),
    }


def build_plan(agent, goal, context):
    """生成计划；模型不可用/输出不合法时降级，不抛异常（取消除外）。"""
    context = context or {}
    files = context.get("files") or []
    llm = (getattr(agent.trunk, "modules", {}) or {}).get("llm")
    if not llm:
        return heuristic_plan(goal, files)
    user = "目标：\n%s\n\n候选文件：\n%s" % (
        goal, ", ".join(str(x) for x in files[:20]) or "（暂无命中，先探索）")
    messages = [{"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": user}]
    try:
        out = agent._llm_chat(llm, messages)
    except Exception as e:
        # 用户取消必须继续向上传播，不能被"降级"吞掉。
        if getattr(agent, "_cancel", None) is not None and agent._cancel.is_set():
            raise
        _x6_swallowed(__name__, e, "build code agent plan")
        return heuristic_plan(goal, files)
    data = agent._extract_json(out) if hasattr(agent, "_extract_json") else None
    return normalize_plan(data, goal, files)


def plan_text(plan):
    """渲染成用户可读文本（审批弹窗 + 时间线共用）。"""
    plan = plan or {}
    lines = ["目标：" + str(plan.get("summary") or "（未提供）")]
    steps = plan.get("steps") or []
    if steps:
        lines.append("")
        lines.append("执行步骤：")
        for i, step in enumerate(steps, 1):
            risk = _RISK_LABELS.get(str(step.get("risk") or ""),
                                    str(step.get("risk") or "中"))
            lines.append("%d. %s（风险：%s）" % (
                i, step.get("title") or "步骤", risk))
            if step.get("purpose"):
                lines.append("   - " + str(step["purpose"]))
            if step.get("files"):
                lines.append("   - 文件：" + ", ".join(
                    str(f) for f in step["files"][:8]))
    if plan.get("risks"):
        lines.append("")
        lines.append("风险提示：")
        for item in plan["risks"][:6]:
            lines.append(" - " + str(item))
    if plan.get("tests"):
        lines.append("")
        lines.append("验证命令：")
        for item in plan["tests"][:6]:
            lines.append(" - " + str(item))
    lines.append("")
    lines.append("确认后才会修改文件；拒绝不会产生任何改动。")
    return "\n".join(lines)


def _set_status(agent, **changes):
    run_id = str(getattr(agent, "_last_run_id", "") or "")
    if not run_id:
        return
    try:
        agent.registry.update_run(run_id, **changes)
    except Exception as e:  # 静默是故意的 - 状态同步失败不阻塞审批
        _x6_swallowed(__name__, e, "update plan run status")


def confirm_plan(agent, goal, context, plan_cb):
    """计划门控：返回 {required, proceed, rejected, plan, reason}。

    只有调用方传入 plan_cb、开关开启、且目标足够复杂时才要求计划。
    """
    files = (context or {}).get("files") or []
    if not callable(plan_cb) or not plan_enabled(agent.trunk) \
            or not needs_plan(goal, files):
        return {"required": False, "proceed": True, "rejected": False,
                "plan": {}, "reason": ""}
    agent._check_control()
    agent._emit("plan_start", {"step": "正在生成执行计划", "progress": 0.12})
    _set_status(agent, status="planning", current_step="生成执行计划",
                progress=0.12)
    plan = build_plan(agent, goal, context)
    text = plan_text(plan)
    agent._emit("plan", {"step": "执行计划已生成", "plan": plan,
                         "text": text, "progress": 0.14})
    _set_status(agent, status="waiting_approval", current_step="等待计划审批",
                progress=0.14)
    agent._emit("plan_wait", {"step": "等待你确认执行计划"})
    decision = plan_cb(plan)
    accepted = decision is not False and decision is not None and not (
        isinstance(decision, dict) and not decision.get("accepted", True))
    if not accepted:
        return {"required": True, "proceed": False, "rejected": True,
                "plan": plan, "reason": "用户拒绝执行计划"}
    agent._check_control()
    _set_status(agent, status="running", current_step="用户已确认计划")
    agent._emit("plan_approved", {"step": "执行计划已确认", "progress": 0.16})
    return {"required": True, "proceed": True, "rejected": False,
            "plan": plan, "reason": ""}
