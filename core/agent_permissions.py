# -*- coding: utf-8 -*-
"""Agent 动作的统一权限、确认和审计入口。

代码 Agent 与电脑 Agent 都从这里走，避免各自直接调用底层能力：
    authorize_agent_action -> PermissionCenter -> 用户确认 once/session/always

`already_approved=True` 用于上层已经展示过等价审批（例如代码 diff 审批）
的场景：仍会先检查硬性禁止/紧急锁定，但不再重复弹第二个确认框。
"""
from __future__ import annotations

import json

from core import security_policy
from core.action_schema import HIGH_RISK_TYPES, READONLY_TYPES


def _subject(kind, action):
    action = action or {}
    return "%s.%s" % (kind, action.get("type") or "action")


def _info(action):
    action = action or {}
    atype = str(action.get("type") or "")
    risk = str(action.get("risk") or "medium")
    # 关键：动作类型可以强制提升风险，模型不能把高危动作标成 low。
    if atype in HIGH_RISK_TYPES:
        risk = "high"
    elif atype in READONLY_TYPES and risk != "high":
        risk = "low"
    readonly = bool(action.get("_readonly")) or risk == "low"
    return {
        "risk": "read" if readonly else ("exec" if atype == "shell" else "write"),
        "readonly": readonly,
        "confirm": (not readonly) and (risk in ("medium", "high")),
        "danger": False,
    }


def _detail(action):
    action = action or {}
    try:
        raw = json.dumps({
            "动作": action.get("type"),
            "目标": action.get("target") or {},
            "参数": action.get("args") or {},
            "原因": action.get("reason") or "",
            "风险": action.get("risk") or "medium",
        }, ensure_ascii=False, indent=2)
    except Exception:
        raw = repr(action)
    return raw[:3500]


def authorize_agent_action(trunk, kind, action, *, title="", detail="",
                           already_approved=False, allow_headless=False):
    """返回 {allow, reason, decision}。

    无 GUI 确认回调时：只读动作放行，写/执行动作 fail-closed。
    测试或后台无界面场景由调用方显式决定是否要求权限。
    """
    if trunk is None:
        return {"allow": False, "reason": "没有运行上下文", "decision": None}
    has_ui = bool(getattr(trunk, "confirm_cb", None))
    headless_ok = bool(allow_headless or
                       getattr(trunk, "allow_headless_agent", False))
    if not has_ui and not headless_ok:
        info = _info(action)
        if info.get("readonly") and not info.get("confirm"):
            return {"allow": True, "reason": "无界面只读动作",
                    "decision": None}
        return {"allow": False,
                "reason": "无可用确认界面，高风险 Agent 动作已按 fail-closed 拒绝",
                "decision": None}

    from core.permission_center import get_permission_center
    pc = get_permission_center(trunk)
    subject = _subject(kind, action)
    info = _info(action)
    decision = pc.authorize(subject, info=info,
                            args=action.get("args") or {},
                            context=action)
    if decision.get("allow"):
        try:
            pc.audit.append({
                "subject": subject, "decision": "allow",
                "result": "agent_authorized",
                "reason": decision.get("reason", "")[:200]})
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass
        return {"allow": True, "reason": decision.get("reason", ""),
                "decision": decision}

    if decision.get("requires_confirm"):
        if not has_ui and headless_ok:
            try:
                pc.audit.append({
                    "subject": subject, "decision": "allow",
                    "result": "headless_explicitly_allowed",
                    "reason": "调用方显式允许无界面执行"})
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                pass
            return {"allow": True, "reason": "显式允许无界面执行",
                    "decision": decision}
        if already_approved:
            try:
                pc.audit.append({
                    "subject": subject, "decision": "allow",
                    "result": "user_confirmed_upstream",
                    "reason": "上层已完成等价审批"})
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                pass
            return {"allow": True, "reason": "上层已审批", "decision": decision}
        text = detail or _detail(action)
        scope = "once"
        scope_cb = getattr(trunk, "confirm_scope_cb", None)
        if callable(scope_cb):
            scope = scope_cb(title or ("执行 Agent 动作：%s" % action.get("type")),
                             text)
        else:
            ok = bool(trunk.confirm(
                title or ("执行 Agent 动作：%s" % action.get("type")), text))
            scope = "once" if ok else "deny"
        if scope not in ("once", "session", "always"):
            try:
                pc.audit.append({
                    "subject": subject, "decision": "deny",
                    "result": "user_cancelled", "reason": "用户取消确认"})
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                pass
            return {"allow": False, "reason": "用户取消确认",
                    "decision": decision}
        if scope in ("session", "always"):
            try:
                pc.approve(
                    subject, scope=scope,
                    reason="用户在 Agent 确认框中选择 %s" % scope,
                    constraints=pc.suggest_constraints(
                        subject, action.get("args") or {}))
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                pass
        try:
            pc.audit.append({
                "subject": subject, "decision": "allow",
                "result": "user_confirmed", "reason": scope})
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass
        return {"allow": True, "reason": "用户确认（%s）" % scope,
                "decision": decision}

    try:
        pc.audit.append({
            "subject": subject, "decision": "deny", "result": "blocked",
            "reason": decision.get("reason", "")[:200]})
    except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
        pass
    return {"allow": False, "reason": decision.get("reason", "操作被拒绝"),
            "decision": decision}


def classify_readonly(action):
    action = action or {}
    try:
        policy = security_policy.classify(
            action.get("type", ""), _info(action))
        return bool(policy.get("readonly")) and not policy.get("confirm")
    except Exception:
        return False
