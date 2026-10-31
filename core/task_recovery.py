# -*- coding: utf-8 -*-
"""任务失败后的恢复建议、trace 聚合与预算调整（2026-10-31 拆分）。

从 `core/task_runtime.py` 拆出（该文件已到 600 行上限）。
`TaskRuntime` 继承本 Mixin，对外行为不变：
`rt.recovery_suggestion / rt.events / rt.increase_budget` 照旧可用，
任务中心与聊天入口的动作分发不需要改。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

try:
    from core.agent_harness import normalize_error as _normalize_error
except ImportError:  # 独立导入时兜底：没有统一错误信封也照样能给出下一步
    def _normalize_error(error, code=None):
        return {"next_action": {}}

# 失败步骤 -> 可执行的恢复建议。顺序：先问用户/补环境，再重试，最后换方案。
_NEED_USER_HINTS = ("需要用户", "无法确定", "补充说明", "请确认", "澄清",
                    "clarify", "ambiguous", "目标不明确")
_BUDGET_HINTS = ("预算", "超时", "timeout", "token", "费用", "max_")
_ENV_ACTIONS = ("open_model_settings", "open_security_center",
                "open_security_network_events", "open_plugin_market")
_STATUS_WHY = {"paused": "任务已暂停，可以继续执行",
               "cancelled": "任务已取消",
               "failed": "任务执行失败"}


class TaskRecoveryMixin:
    def recovery_suggestion(self, task_id, step_id=None):
        """失败后的唯一下一步：为什么失败 + 可执行动作。

        返回 {ok, why, action, label, step_id, step_title, attempts}。
        action 与任务中心 / 聊天的动作分发保持一致：
        retry_failed_step / increase_task_budget / replan / ask_user /
        open_model_settings / open_security_center / open_plugin_market。
        """
        task = self.get_task(task_id)
        if not task:
            return {"ok": False, "错误": "任务不存在"}
        steps = task.get("steps") or []
        step = next((s for s in steps if s.get("id") == step_id), None) \
            if step_id else None
        if step is None:
            step = next((s for s in steps
                         if s.get("status") == "failed"), None)
        error = str((step or {}).get("error") or task.get("error") or "")
        status = str(task.get("status") or "")
        attempts = int((step or {}).get("attempts", 0) or 0)
        why = error or _STATUS_WHY.get(status, "任务没有完成")
        # 1. 目标本身不清楚：先问用户，盲目重试只会重复失败。
        low = error.lower()
        if any(h in error or h in low for h in _NEED_USER_HINTS):
            return self._recovery("ask_user", "补充目标信息后再继续",
                                  why, step)
        # 2. 超时 / 预算：加预算比重新拆解更省事。
        if any(h in error or h in low for h in _BUDGET_HINTS):
            return self._recovery("increase_task_budget", "增加预算并继续",
                                  why, step)
        # 3. 模型/权限/网络/工具缺失：走现有的设置与安全入口。
        try:
            env = _normalize_error(error)
            action = str((env.get("next_action") or {}).get("id") or "")
            label = str((env.get("next_action") or {}).get("label") or "")
        except Exception:  # 静默是故意的 - 分类失败不影响重试
            action, label = "", ""
        if action in _ENV_ACTIONS:
            return self._recovery(action, label or "去处理", why, step)
        # 4. 同一步已经失败两次：换方案，不要继续原地重试。
        if attempts >= 2:
            return self._recovery("replan", "换个做法重新拆解", why, step)
        # 5. 默认：只重试失败步骤，已完成的不重跑。
        return self._recovery("retry_failed_step", "重试这一步", why, step)

    @staticmethod
    def _recovery(action, label, why, step):
        return {"ok": True, "action": action, "label": label,
                "why": str(why)[:500],
                "step_id": (step or {}).get("id", ""),
                "step_title": (step or {}).get("title", ""),
                "attempts": int((step or {}).get("attempts", 0) or 0)}

    def events(self, task_id, step_id=None, limit=50):
        """任务中心失败步骤处的 trace 聚合（时间正序，最近 limit 条）。"""
        try:
            rows = self.trace.read(500)
        except Exception as e:
            _x6_swallowed(__name__, e, "read task trace")
            rows = []
        out = [e for e in rows if e.get("task_id") == task_id
               and (not step_id or e.get("step_id") == step_id)]
        return out[-max(1, int(limit)):]

    def increase_budget(self, task_id, *, seconds=120, steps=4, tokens=5000,
                        tool_calls=10):
        """任务超时 / 预算不足时，增加预算并保留已完成步骤。"""
        task = self.get_task(task_id)
        if not task:
            return {"ok": False, "错误": "任务不存在"}
        budget = task.setdefault("budget", {})
        budget["max_seconds"] = int(budget.get("max_seconds", 300)) + int(seconds)
        budget["max_steps"] = int(budget.get("max_steps", 8)) + int(steps)
        budget["max_tokens"] = int(budget.get("max_tokens", 20000)) + int(tokens)
        budget["max_tool_calls"] = int(
            budget.get("max_tool_calls", 20)) + int(tool_calls)
        self._save(task)
        self._emit(task, "budget_increased",
                   "seconds+%s steps+%s" % (seconds, steps))
        return {"ok": True, "task_id": task_id, "budget": budget}
