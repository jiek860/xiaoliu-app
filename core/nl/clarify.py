# -*- coding: utf-8 -*-
"""澄清与计划卡（批次 44.3）。

两个原则：
    · 缺槽位时**只问一个**最关键的问题；能从上下文（当前文件/选区/最近报错）
      补上的就不再问；
    · 复杂任务复用 ``core/code_plan`` 的启发式计划，输出带 ``done`` 的步骤，
      界面可直接渲染成可勾选清单，不另造一套计划结构。
"""
from __future__ import annotations

from core.code_plan import heuristic_plan, needs_plan, normalize_plan
from core.nl.intent import clarify_question

_CLARIFY_INTENTS = ("open_file", "run_test", "explain", "fix_error",
                    "edit_code", "refactor", "plan", "search", "undo")


def _has_target(info, kinds=("file", "symbol", "test")):
    return any(t.get("type") in kinds for t in (info or {}).get("targets") or [])


def missing_slot(info):
    """返回缺失的关键槽位名；不缺返回 ""。"""
    info = info or {}
    intent = info.get("intent", "chat")
    if intent == "run_test" and not info.get("run_all_tests") and \
            not _has_target(info, ("test", "file")):
        return "test"
    if intent == "search" and not (info.get("query") or _has_target(info)):
        return "query"
    if intent in ("open_file", "explain", "fix_error", "edit_code",
                  "refactor") and not _has_target(info):
        return "target"
    return ""


def fill_from_context(info, context=None):
    """用上下文补槽位：当前文件 / 选区 / 最近报错。"""
    out = dict(info or {})
    ctx = dict(context or {})
    if not missing_slot(out):
        return out
    current = str(ctx.get("current_file") or ctx.get("open_file") or "").strip()
    if current and out.get("intent") in ("open_file", "explain", "fix_error",
                                         "edit_code", "refactor"):
        targets = list(out.get("targets") or [])
        targets.append({"type": "file", "value": current})
        out["targets"] = targets
        out["context_filled"] = "current_file"
    if out.get("intent") == "search" and not out.get("query"):
        selection = str(ctx.get("selection") or "").strip()
        if selection:
            out["query"] = selection[:40]
            out["context_filled"] = "selection"
    if out.get("intent") == "fix_error" and not out.get("error"):
        error = str(ctx.get("last_error") or "").strip()
        if error:
            out["error"] = error[:300]
    if not missing_slot(out):
        out["clarify"] = ""
        out["stage"] = "ready"
    return out


def ask(info, *, resolved=None, context=None, round=1):
    """生成一个澄清问题；已具备槽位时返回 kind=ready。

    ``round``（批次 D8）：多轮追问时把轮次透传给 ``clarify_question``，
    同一槽位没补上时换成更具体的提示，而不是重复同一句话。
    """
    info = fill_from_context(info, context)
    slot = missing_slot(info)
    # 只有“必须落到某个对象”的意图才被实体候选卡住；搜索有关键词就够
    needs_entity = info.get("intent") in (
        "open_file", "explain", "fix_error", "edit_code", "refactor",
        "run_test")
    unresolved = [r for r in (resolved or [])
                  if not r.get("ok")] if needs_entity else []
    # 槽位写全了、但实体解析不到（同名候选多个）——仍要问一句再动手
    if not slot and not unresolved:
        return {"kind": "ready", "question": "", "options": [],
                "info": info}
    if not slot:
        slot = "entity"
    options = []
    for item in unresolved:
        for name in item.get("candidates") or []:
            if name and name not in options:
                options.append(name)
    options = options[:5]
    if options:
        question = "我没确定是哪一个，你指的是下面哪个？"
    else:
        question = clarify_question(info, round) or "能再说清楚一点吗？"
    return {"kind": "clarify", "question": question, "options": options,
            "slot": slot, "info": info}


def merge_goal(original, answer):
    """多轮澄清闭环（批次 D8）：把追问的回答拼回完整目标。

    工作台的目标是自由文本，直接拼一句「补充：…」比重新猜意图更稳：
    原句里的意图/动词保留，用户的补充当成追加约束再走一次 ``route``。
    """
    base = str(original or "").strip()
    text = str(answer or "").strip()
    if not text:
        return base
    if not base:
        return text
    if text in base:            # 用户重述整句时不要重复拼接
        return base
    return base + "\n补充：" + text


def merge_answer(info, answer, *, context=None):
    """把用户对追问的回答并回意图：有候选就选第一个匹配，否则补文件。"""
    out = fill_from_context(info, context)
    text = str(answer or "").strip()
    if not text:
        return out
    if out.get("intent") == "search" and not out.get("query"):
        out["query"] = text[:80]
    elif text.lower() in ("全部", "所有", "全量"):
        out["run_all_tests"] = True
    elif out.get("intent") == "run_test" and not _has_target(
            out, ("test", "file")):
        out["targets"] = list(out.get("targets") or []) + [
            {"type": "test", "value": text}]
    else:
        kind = "file" if "." in text else "symbol"
        if kind == "file" and "/" not in text and "\\" not in text:
            kind = "symbol"
        out["targets"] = list(out.get("targets") or []) + [
            {"type": kind, "value": text}]
    if not missing_slot(out):
        out["clarify"] = ""
        out["stage"] = "ready"
    return out


def _steps(plan):
    steps = []
    for index, step in enumerate((plan or {}).get("steps") or []):
        item = dict(step) if isinstance(step, dict) else {"title": str(step)}
        item["done"] = False
        item["index"] = index
        steps.append(item)
    return steps


def plan_card(goal, *, info=None, context=None, data=None):
    """计划卡：复用 code_plan，复杂任务才出；步骤可勾选。"""
    goal = str(goal or "").strip()
    info = fill_from_context(info or {}, context)
    files = [t.get("value") for t in info.get("targets") or []
             if t.get("type") in ("file", "symbol")][:8]
    plan = (normalize_plan(data, goal, files) if data
            else heuristic_plan(goal, files))
    steps = _steps(plan)
    return {
        "goal": goal,
        "summary": str(plan.get("summary") or goal)[:200],
        "steps": steps,
        "risks": list(plan.get("risks") or []),
        "tests": list(plan.get("tests") or []),
        "fallback": bool(plan.get("fallback")),
        "editable": True,
        "intent": info.get("intent", ""),
        "scope": info.get("scope", ""),
        "needs_plan": needs_plan(goal, files),
        "confirm_text": "确认后按步骤执行；每一步都可以取消勾选。",
    }
