# -*- coding: utf-8 -*-
"""统一 Agent 旅程编排器。

一个入口接收用户目标，自动选择：
    代码 Agent / 电脑 Agent / 普通对话
并把路由、执行事件、审批、暂停取消、回滚统一成一套接口。
"""
from __future__ import annotations

import time

from core.agent_harness import get_run_registry, normalize_error
from core.agent_router import route_goal, route_label


class AgentOrchestrator:
    def __init__(self, trunk, root=None, event_cb=None, approval_cb=None,
                 max_steps=12, open_files=None, selection=""):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.root = root or self.base
        self.event_cb = event_cb
        self.approval_cb = approval_cb
        self.max_steps = max(1, int(max_steps or 12))
        self.open_files = list(open_files or [])
        self.selection = str(selection or "")
        self.current_agent = None
        self.current_kind = ""
        self.last_result = None
        self.registry = get_run_registry()

    def route(self, goal):
        return route_goal(goal, has_code_root=bool(self.root))

    def _emit(self, event, data=None):
        try:
            if callable(self.event_cb):
                self.event_cb(event, data or {})
        except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            pass

    def _approve_code(self, patch):
        if not callable(self.approval_cb):
            return True
        return self.approval_cb("code", patch)

    def _approve_computer(self, actions):
        if not callable(self.approval_cb):
            return True
        return bool(self.approval_cb("computer", actions))

    def run(self, goal, *, explicit=None, approval_cb=None, event_cb=None,
            max_steps=None):
        goal = str(goal or "").strip()
        if not goal:
            return {"ok": False, "error": "目标为空"}
        if callable(approval_cb):
            self.approval_cb = approval_cb
        if callable(event_cb):
            self.event_cb = event_cb
        route = self.route(goal)
        if explicit:
            from core.agent_router import route_goal
            route = route_goal(goal, has_code_root=True, explicit=explicit)
        kind = route.get("kind", "chat")
        self.current_kind = kind
        self._emit("route", {"step": "已选择执行域：%s" % route_label(route),
                             "route": route, "goal": goal,
                             "progress": 0.01})
        try:
            if kind == "code":
                from core.code_agent import CodeAgent
                agent = CodeAgent(
                    self.trunk, self.root, event_cb=self.event_cb,
                    approval_cb=self._approve_code,
                    open_files=self.open_files,
                    selection=self.selection)
                self.current_agent = agent
                result = agent.run(
                    goal, max_rounds=3,
                    approved_cb=(self._approve_code
                                 if callable(self.approval_cb) else None))
                result["kind"] = "code"
                result["route"] = route
                self.last_result = result
                return result

            if kind == "computer":
                from core.computer_agent import ComputerAgent
                agent = ComputerAgent(
                    self.trunk, event_cb=self.event_cb,
                    max_steps=max_steps or self.max_steps)
                self.current_agent = agent
                result = agent.run_goal_dynamic(
                    goal, max_steps=max_steps or self.max_steps,
                    approval_cb=(self._approve_computer
                                 if callable(self.approval_cb) else None))
                result["kind"] = "computer"
                result["route"] = route
                self.last_result = result
                return result

            self._emit("chat_start", {"step": "交给对话模型处理",
                                      "progress": 0.1})
            on_token = None
            ans = self.trunk.reply(goal, on_token=on_token)
            result = {"ok": True, "kind": "chat", "answer": str(ans or ""),
                      "route": route}
            self.last_result = result
            self._emit("done", {"step": "对话完成", "result": result["answer"],
                                "progress": 1.0})
            return result
        except Exception as e:
            env = normalize_error(e)
            self._emit("failed", {"step": env.get("title", "任务失败"),
                                  "error": env.get("message", ""),
                                  "progress": 1.0})
            result = {"ok": False, "kind": kind, "error": env.get("message"),
                      "envelope": env, "route": route}
            self.last_result = result
            return result

    def pause(self):
        agent = self.current_agent
        if agent is not None and hasattr(agent, "pause"):
            agent.pause()
            self._emit("paused", {"step": "任务已暂停，可人工接管"})
            return {"ok": True}
        return {"ok": False, "error": "当前没有可暂停的 Agent"}

    def resume(self):
        agent = self.current_agent
        if agent is not None and hasattr(agent, "resume"):
            agent.resume()
            self._emit("resumed", {"step": "任务继续"})
            return {"ok": True}
        return {"ok": False, "error": "当前没有可继续的 Agent"}

    def cancel(self):
        agent = self.current_agent
        if agent is not None and hasattr(agent, "cancel"):
            agent.cancel()
            self._emit("cancels_requested", {"step": "正在取消任务"})
            return {"ok": True}
        return {"ok": False, "error": "当前没有可取消的 Agent"}

    def rollback(self):
        agent = self.current_agent
        result = self.last_result or {}
        if agent is None:
            return {"ok": False, "error": "没有可回滚的任务"}
        if self.current_kind == "code" and hasattr(agent, "rollback_all"):
            return agent.rollback_all(result.get("backups") or [])
        if self.current_kind == "computer" and hasattr(agent, "rollback_run"):
            return agent.rollback_run(result.get("run_id", ""))
        return {"ok": False, "error": "当前任务没有可回滚操作"}

    def describe(self, goal):
        info = self.route(goal)
        info["label"] = route_label(info)
        return info
