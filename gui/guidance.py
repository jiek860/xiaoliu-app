# -*- coding: utf-8 -*-
"""下一步引导引擎。

原则：每个失败/空状态只给一个最明确、可执行的动作。
引导完成状态写入 data/ui_state.json（与 UI 模式共用一份状态文件）。
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

from gui.ui_mode import load_ui_state, save_ui_state


# 事件 -> 面向用户的一句话 + 唯一动作
GUIDANCE = {
    "first_run": {
        "title": "先配好模型",
        "message": "支持 Windows 10/11 + Python 3.10~3.12。打开设置，选本地或云端模型；配好后就能开始聊天。",
        "action_label": "去设置模型",
        "action": "open_model_settings",
    },
    "model_not_configured": {
        "title": "模型还没配置好",
        "message": "当前回复可能失败，先完成模型配置；旧数据会在启动时自动备份并迁移。",
        "action_label": "去设置模型",
        "action": "open_model_settings",
    },
    "first_chat": {
        "title": "说第一句话",
        "message": "在输入框里问一个问题，或者直接说你想做什么。",
        "action_label": "开始聊天",
        "action": "focus_input",
    },
    "first_task": {
        "title": "试一个任务",
        "message": "把复杂目标交给任务模式，它会拆成计划并逐步执行。",
        "action_label": "开始任务",
        "action": "start_task",
    },
    "first_kb_import": {
        "title": "导入第一份资料",
        "message": "打开资料/知识库，导入文档后就能基于资料回答。",
        "action_label": "去导入资料",
        "action": "open_knowledge_base",
    },
    "permission_denied": {
        "title": "权限被拒绝",
        "message": "这次操作没有获得授权，可以重新授权或去安全中心查看原因。",
        "action_label": "重新授权 / 去安全中心",
        "action": "open_security_center",
    },
    "task_failed": {
        "title": "任务失败",
        "message": "先重试失败步骤；如果仍然失败，再查看日志定位原因。",
        "action_label": "重试失败步骤",
        "action": "retry_failed_step",
    },
    "tool_missing": {
        "title": "工具不存在",
        "message": "当前模块没有提供这个工具，去插件市场安装或启用对应模块。",
        "action_label": "去插件市场",
        "action": "open_plugin_market",
    },
    "network_denied": {
        "title": "网络被拒绝",
        "message": "安全策略拦截了这次网络请求，去安全中心查看网络事件。",
        "action_label": "查看安全中心网络事件",
        "action": "open_security_network_events",
    },
    "task_timeout": {
        "title": "任务超时",
        "message": "可以增加任务预算后继续，或者把目标拆小一点再试。",
        "action_label": "增加预算 / 继续任务",
        "action": "increase_task_budget",
    },
    "file_conflict": {
        "title": "文件已被修改",
        "message": "目标文件在应用补丁前发生了变化，已停止覆盖。",
        "action_label": "查看 diff / 重新生成",
        "action": "review_diff",
    },
    "test_failed": {
        "title": "测试未通过",
        "message": "修改已应用，但测试没有通过；可以自动修复或查看失败测试。",
        "action_label": "自动修复失败测试",
        "action": "auto_fix_failed_tests",
    },
}

# 根据错误文本推断唯一下一步。顺序有讲究：先具体，后泛化。
_ERROR_RULES = (
    ("model_not_configured", ("模型未配置", "模型没配置", "llm未加载",
                              "api key", "no model")),
    ("network_denied", ("网络被拒绝", "网络策略", "network denied", "net_guard")),
    ("permission_denied", ("权限", "拒绝", "denied", "forbidden", "unauthorized")),
    ("tool_missing", ("工具不存在", "没有方法", "not found", "no such tool")),
    ("task_timeout", ("任务超时", "timeout", "超时")),
    ("task_failed", ("失败", "错误", "failed", "error")),
)


def classify_error(error: str) -> str:
    """统一使用 core.agent_harness 的错误分类，避免两套规则漂移。"""
    try:
        from core.agent_harness import normalize_error
        code = normalize_error(error)["code"].lower()
        return {"tool_not_found": "tool_missing"}.get(code, code)
    except Exception:  # 静默是故意的
        text = str(error or "").lower()
        for event, needles in _ERROR_RULES:
            if any(n.lower() in text for n in needles):
                return event
        return "task_failed"


def next_step(event: str) -> Dict:
    item = GUIDANCE.get(event) or GUIDANCE["task_failed"]
    return {"event": event, **item}


def next_step_for_error(error: str) -> Dict:
    return next_step(classify_error(error))


class GuidanceEngine:
    """引导状态机。所有 UI 只调用这里，不各自维护看没看过的布尔值。"""

    def __init__(self, base: str, trunk=None):
        self.base = base
        self.trunk = trunk
        self._state = load_ui_state(base)
        if not isinstance(self._state.get("guidance"), dict):
            self._state["guidance"] = {
                "completed": [], "seen": [], "last_event": ""}

    @property
    def state(self) -> Dict:
        return json.loads(json.dumps(self._state))

    def _g(self) -> Dict:
        return self._state.setdefault("guidance", {})

    def is_done(self, event: str) -> bool:
        return event in (self._g().get("completed") or [])

    def mark_done(self, event: str) -> Dict:
        g = self._g()
        completed = list(g.get("completed") or [])
        if event and event not in completed:
            completed.append(event)
        g["completed"] = completed
        g["last_event"] = event
        self._state["guidance"] = g
        self._state = save_ui_state(self.base, self._state)
        return self.state

    def mark_seen(self, event: str) -> None:
        g = self._g()
        seen = list(g.get("seen") or [])
        if event and event not in seen:
            seen.append(event)
        g["seen"] = seen
        g["last_event"] = event
        self._state = save_ui_state(self.base, self._state)

    def reset(self) -> None:
        self._state["guidance"] = {"completed": [], "seen": [], "last_event": ""}
        self._state = save_ui_state(self.base, self._state)

    def _model_ready(self) -> bool:
        if self.trunk is None:
            return True
        try:
            from core import model_setup
            return bool(model_setup.check(self.trunk, probe=False).get("ready"))
        except Exception:
            return True

    def current(self) -> Dict:
        """返回当前最该显示的引导；已完成的引导不再打扰。"""
        if not self.is_done("first_run") and not self._model_ready():
            return next_step("model_not_configured")
        if not self.is_done("first_chat"):
            return next_step("first_chat")
        if not self.is_done("first_task"):
            return next_step("first_task")
        if not self.is_done("first_kb_import"):
            return next_step("first_kb_import")
        return {}

    def empty_state_cards(self) -> list:
        cards = []
        for event in ("model_not_configured", "first_chat", "first_task"):
            item = next_step(event)
            item["done"] = self.is_done(event)
            cards.append(item)
        # 模型配置完成时，第一张卡改成资料
        if self._model_ready():
            kb = next_step("first_kb_import")
            kb["done"] = self.is_done("first_kb_import")
            cards[0] = kb
        return cards

    def for_error(self, error: str) -> Dict:
        return next_step_for_error(error)

    def action(self, event_or_action: str) -> str:
        """把事件或动作统一归一成 action id，便于 UI 分发。"""
        e = str(event_or_action or "")
        if e in GUIDANCE:
            return GUIDANCE[e]["action"]
        return e
