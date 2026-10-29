# -*- coding: utf-8 -*-
"""命令中心的自然语言决策层（批次 44.4）。

只做“这句话该怎么处理”，不碰 Qt：
    command  → 调用方自己先查命令名，这里不参与
    nl       → 可执行动作（open / run_test / search / ai / undo）
    file     → 不是工作台意图，回退旧的文件名打开
    clarify  → 缺槽位或候选不唯一，只回一句问题
    not_found→ 目标写了但搜不到，给出明确提示

撤销复用 ``core.patch_engine`` 的备份清单（``data/patch_backups``），
不另造一套回滚机制。
"""
from __future__ import annotations

import json
import os
import re

from core.nl.clarify import ask
from core.nl.entities import resolve_targets
from core.nl.intent import route

_AI_INTENTS = ("explain", "fix_error", "edit_code", "refactor", "plan")


def _reference(text):
    """``@file`` / ``@symbol``：显式引用优先，不再走关键词。"""
    token = str(text or "").lstrip("@").strip()
    kind = "file" if ("." in token or "/" in token or "\\" in token) else "symbol"
    intent = "open_file" if kind == "file" else "explain"
    return {"intent": intent, "confidence": 0.95, "reason": "@ 引用",
            "stage": "rule", "targets": [{"type": kind, "value": token}],
            "scope": "file", "constraints": [], "risk": "low",
            "clarify": "", "query": "", "auto_execute": True,
            "text": str(text or "")}


def _first_path(resolved, kind):
    for item in resolved or []:
        if item.get("type") == kind and item.get("ok") and item.get("path"):
            return item["path"]
    return ""


def _target_value(info, kind):
    for item in info.get("targets") or []:
        if item.get("type") == kind:
            return str(item.get("value") or "")
    return ""


def _action(info, resolved, text):
    intent = info.get("intent", "chat")
    if intent == "open_file":
        path = _first_path(resolved, "file") or _target_value(info, "file")
        return {"action": "open", "path": path} if path else None
    if intent == "run_test":
        path = _first_path(resolved, "test")
        if not path:
            path = _first_path(resolved, "file")
        return {"action": "run_test", "path": path}
    if intent == "search":
        return {"action": "search",
                "query": info.get("query") or str(text or "")}
    if intent == "undo":
        return {"action": "undo"}
    if intent in _AI_INTENTS:
        goal = re.sub(r"^/[\w]+\s*", "", str(text or "")).strip()
        return {"action": "ai", "intent": intent, "goal": goal or str(text or "")}
    return None


def _not_found(info, resolved):
    missing = [r for r in resolved or [] if not r.get("ok")]
    if not missing:
        return ""
    value = missing[0].get("value") or ""
    return "没找到「%s」，换个文件名或符号名再试。" % value


def plan_command(text, *, root=".", index=None, context=None):
    """把一行输入变成可执行动作；不执行、不弹窗。"""
    text = str(text or "").strip()
    if not text:
        return {"kind": "none", "info": {}}
    info = _reference(text) if text.startswith("@") else route(
        text, context=context)
    if info.get("intent") == "chat" and not text.startswith("@"):
        return {"kind": "file", "text": text, "info": info}
    resolved = resolve_targets(info.get("targets") or [], root=root,
                               index=index)
    info["resolved"] = resolved
    reply = ask(info, resolved=resolved, context=context)
    if reply["kind"] == "clarify":
        missing = _not_found(info, resolved)
        if missing and not reply["options"] and \
                info.get("intent") == "open_file":
            return {"kind": "not_found", "message": missing, "info": info}
        return {"kind": "clarify", "question": reply["question"],
                "options": reply["options"], "info": info}
    action = _action(reply["info"], resolved, text)
    if action is None:
        return {"kind": "file", "text": text, "info": info}
    return {"kind": "nl", "action": action, "info": reply["info"],
            "text": text}


def backup_dir(root):
    return os.path.join(str(root or "."), "data", "patch_backups")


def latest_manifest(root):
    """最近一次自动修改的备份清单；没有返回 ""。"""
    base = backup_dir(root)
    found = []
    try:
        names = os.listdir(base)
    except OSError:
        return ""
    for name in names:
        path = os.path.join(base, name, "manifest.json")
        if not os.path.isfile(path):
            continue
        created = 0.0
        try:
            with open(path, encoding="utf-8") as fp:
                created = float(json.load(fp).get("created_at") or 0)
        except (OSError, ValueError, TypeError):
            created = 0.0
        found.append((created, name, path))
    if not found:
        return ""
    found.sort(key=lambda x: (-x[0], x[1]))
    return found[0][2]


def undo_last(root, *, dry_run=False):
    """撤销最近一次自动修改；dry_run 只返回清单路径。"""
    path = latest_manifest(root)
    if not path:
        return {"ok": False, "error": "没有可撤销的自动修改"}
    if dry_run:
        return {"ok": True, "manifest": path, "restored": []}
    try:
        from core.patch_engine import rollback
        result = rollback(path)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "manifest": path}
    return {"ok": True, "manifest": path,
            "restored": result.get("restored") or []}
