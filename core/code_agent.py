# -*- coding: utf-8 -*-
"""代码 Agent：项目上下文 -> 探索工具 -> patch -> 审批 -> 测试 -> 回修 -> 回滚。

在原有最小闭环上补齐：
* 可中断 / 可暂停 / 可超时的命令执行；
* 读文件、grep、列目录、查符号、运行白名单命令等探索工具；
* 自动探测 pytest / unittest / npm / cargo / go 测试与 lint；
* update/create/delete/rename/write 多文件 patch；
* 每轮事件推送、失败回修、完整回滚清单；
* 所有写操作统一经过 Agent 权限审计。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from core.agent_harness import get_run_registry, normalize_error
from core.agent_permissions import authorize_agent_action
from core.code_agent_policy import (
    describe as describe_rounds,
    evaluate_round,
    resolve_max_rounds,
)
from core.patch_engine import (
    PatchError, apply_patch, dry_run_patch, file_patch, rollback, sha256_file,
    unified_diff, validate_patch,
)
from core.path_safety import safe_join
from core.workspace_index import WorkspaceIndex

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class AgentCancelled(RuntimeError):
    pass


from core.code_context import CodeContextMixin
from core.code_explorer import CodeExplorerMixin
from core.code_command_runner import CodeCommandRunnerMixin
from core.code_git_tools import CodeGitToolsMixin


class CodeAgent(
    CodeContextMixin,
    CodeExplorerMixin,
    CodeCommandRunnerMixin,
    CodeGitToolsMixin,
):
    def __init__(self, trunk, root=None, test_commands=None,
                 approval_cb=None, event_cb=None, lint_commands=None,
                 open_files=None, selection=""):
        self.trunk = trunk
        self.root = os.path.abspath(root or getattr(trunk, "base", "."))
        self.test_commands = list(test_commands or [])
        self.lint_commands = list(lint_commands or [])
        self.approval_cb = approval_cb
        self.event_cb = event_cb
        self.index = WorkspaceIndex(getattr(trunk, "base", self.root), self.root)
        self.registry = get_run_registry()
        self.open_files = [str(x) for x in (open_files or []) if x]
        self.selection = str(selection or "")
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._active_proc = None
        self._proc_lock = threading.RLock()
        self._last_backups = []
        self._last_run_id = ""

    def cancel(self):
        self._cancel.set()
        self._kill_active_proc()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def is_paused(self):
        return self._pause.is_set()

    def _check_control(self):
        if self._cancel.is_set():
            raise AgentCancelled("任务已取消")
        while self._pause.is_set():
            if self._cancel.is_set():
                raise AgentCancelled("任务已取消")
            time.sleep(0.15)

    def _sleep(self, seconds):
        end = time.time() + max(0.0, float(seconds or 0))
        while time.time() < end:
            self._check_control()
            time.sleep(min(0.1, end - time.time()))

    def _kill_active_proc(self):
        with self._proc_lock:
            proc = self._active_proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                if os.name == "nt":
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
                else:
                    proc.kill()
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _emit(self, event, data=None):
        payload = {"event": str(event), "data": data or {},
                   "run_id": self._last_run_id, "time": time.time()}
        try:
            if callable(self.event_cb):
                self.event_cb(event, data or {})
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        if self._last_run_id:
            try:
                step = str((data or {}).get("step") or event)
                progress = (data or {}).get("progress")
                changes: dict[str, object] = {"current_step": step}
                if isinstance(progress, (int, float)):
                    changes["progress"] = max(0.0, min(1.0, float(progress)))
                changes["metadata"] = {"last_event": event,
                                       "detail": str(data or "")[:500]}
                self.registry.update_run(self._last_run_id, **changes)
            except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                _x6_swallowed(__name__, e, "best-effort fallback")
        self._append_trace(payload)

    def _append_trace(self, payload):
        try:
            import json as _json
            d = os.path.join(self.root, "data", "agent_runs")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "code_events.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception as e:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
            _x6_swallowed(__name__, e, "best-effort fallback")

    def prepare(self, goal, previous_error=""):
        self._check_control()
        context = self.build_context(goal)
        self._emit("context", {"step": "已收集项目上下文",
                               "files": context.get("files", []),
                               "progress": 0.1})
        patch = self.propose_patch(goal, context, previous_error)
        return {"ok": True, "patch": patch, "context_files": context.get("files", [])}

    def apply_and_test(self, patch, approved_upstream=False):
        action = {"type": "edit_file", "risk": "high",
                  "args": {"path": ",".join(
                      f.get("path", "") for f in patch.get("files", []))},
                  "reason": patch.get("goal", "")}
        gate = authorize_agent_action(
            self.trunk, "code_agent", action,
            title="代码 Agent 修改文件",
            detail=unified_diff(self.root, patch)[:3000],
            already_approved=approved_upstream)
        if not gate.get("allow"):
            return {"ok": False, "error": gate.get("reason"),
                    "permission": gate}
        self._emit("apply", {"step": "正在应用修改", "progress": 0.45,
                             "files": [x.get("path") for x in patch.get("files", [])]})
        applied = apply_patch(self.root, patch)
        self._last_backups.append(applied.get("backup_manifest"))
        self._emit("applied", {"step": "修改已应用",
                               "applied": applied.get("applied") or [],
                               "progress": 0.5})
        self._emit("tests_start", {"step": "正在运行测试与 lint", "progress": 0.62})
        tests = self.run_tests()
        lint = self.run_lint()
        return {"ok": bool(tests.get("ok") and lint.get("ok")),
                "applied": applied, "tests": tests, "lint": lint,
                "backups": [applied.get("backup_manifest")]}

    def run(self, goal, *, max_rounds=None, approved_cb=None,
            resume_state=None, checkpoint_cb=None):
        """执行代码任务。

        `max_rounds` 为 None 时按 显式参数 > 环境变量 > 配置 > 默认 12 解析。
        `resume_state` 用于断点续跑（轮次、错误、备份清单、错误指纹）。
        `checkpoint_cb(state)` 每轮结束回调，任务队列用它落盘。
        """
        max_rounds = resolve_max_rounds(max_rounds, self.trunk)
        self.max_rounds = max_rounds
        resume_state = dict(resume_state or {})
        run_id = "code_agent:" + str(int(time.time() * 1000))
        self._last_run_id = run_id
        try:
            from core.agent_artifacts import maybe_cleanup
            maybe_cleanup(self.root)
        except Exception as e:  # 静默是故意的 - 清理失败不影响任务
            _x6_swallowed(__name__, e, "best-effort fallback")
        self.registry.start_run("code_agent", goal[:80], run_id=run_id,
                                budget={"max_seconds": 900})
        approval_cb = approved_cb or self.approval_cb
        backups: list[str] = list(resume_state.get("backups") or [])
        last_error = str(resume_state.get("last_error") or "")
        start_round = max(1, int(resume_state.get("round") or 1))
        fingerprints = list(resume_state.get("fingerprints") or [])
        patch_history = list(resume_state.get("patches") or [])
        previous_diff = str(resume_state.get("last_diff") or "")
        tests: dict = {}
        lint: dict = {}
        applied: dict = {}
        git: dict = {}
        stop_reason = "max_rounds"
        try:
            self._emit("run_start", {"step": "准备代码任务", "progress": 0.02,
                                     "max_rounds": max_rounds,
                                     "resume_from": start_round - 1,
                                     "policy": describe_rounds(max_rounds)})
            git = self.git_protect()
            if git.get("dirty"):
                self._emit("git_dirty", {"step": "检测到未提交修改",
                                         "detail": git.get("status", "")[:1000],
                                         "backup": git.get("dirty_backup", "")})
            context = self.build_context(goal)
            self._emit("context", {"step": "已收集项目上下文",
                                   "files": context.get("files", []),
                                   "progress": 0.1})
            def _round_failed(message):
                """某一轮没有产出可应用的修改：记下原因，决定是否继续。

                生成/校验失败不再直接结束整个任务 —— 把错误当回修线索
                带进下一轮，模型还有机会修正 JSON 或 hunk 的原文匹配。
                """
                message = str(message or "本轮没有产出可应用的修改")
                self._emit("patch_error", {"step": "本轮修改无效，准备重修",
                                           "error": message[:2000],
                                           "round": round_no})
                verdict = evaluate_round(
                    round_no=round_no, max_rounds=max_rounds,
                    tests={"ok": False,
                           "results": [{"ok": False, "output": message}]},
                    lint={"ok": True}, fingerprint_history=fingerprints,
                    patch_history=patch_history, patch_id="")
                reason = str(verdict.get("reason") or "max_rounds")
                self._emit("round_end", {
                    "step": "第 %d 轮：%s" % (round_no, verdict.get("message", "")),
                    "round": round_no, "max_rounds": max_rounds,
                    "reason": reason, "stop": bool(verdict.get("stop")),
                    "progress": min(0.9, 0.7 + round_no * 0.02)})
                fingerprints.append(str(verdict.get("fingerprint") or ""))
                patch_history.append("")
                if callable(checkpoint_cb):
                    try:
                        checkpoint_cb({
                            "round": round_no + 1, "max_rounds": max_rounds,
                            "last_error": message, "last_diff": previous_diff,
                            "fingerprints": fingerprints,
                            "patches": patch_history,
                            "backups": list(backups),
                            "stop_reason": reason,
                            "done": bool(verdict.get("stop")),
                        })
                    except Exception as e:  # 静默是故意的 - 断点保存失败不阻塞
                        _x6_swallowed(__name__, e, "save code agent checkpoint")
                if not verdict.get("stop"):
                    return None
                self.registry.finish_run(run_id, "failed", message)
                self._emit("failed", {"step": str(verdict.get("message") or ""),
                                      "error": message[:4000],
                                      "stop_reason": reason, "progress": 1.0})
                return {"ok": False, "run_id": run_id, "error": message,
                        "stop_reason": reason, "rounds_used": round_no,
                        "max_rounds": max_rounds, "tests": tests, "lint": lint,
                        "backups": backups, "git": git}

            for round_no in range(start_round, max_rounds + 1):
                self._check_control()
                self.registry.update_run(
                    run_id, current_step="生成第 %d 轮 patch" % round_no,
                    progress=min(0.15 + round_no * 0.12, 0.55))
                # 回修前重新读项目：上一轮 patch 已经落盘，旧上下文可能过期。
                if round_no > 1:
                    context = self.build_context(goal)
                try:
                    patch = self.propose_patch(goal, context, last_error,
                                               previous_diff=previous_diff)
                except AgentCancelled:
                    raise
                except PatchError as e:
                    failed = _round_failed(str(e))
                    if failed:
                        return failed
                    last_error = str(e)
                    continue
                self._check_control()
                self._emit("patch", {"step": "生成修改方案",
                                     "patch": patch,
                                     "progress": 0.25 + round_no * 0.1})
                decision = None
                if callable(approval_cb):
                    self.registry.update_run(run_id, current_step="等待修改审批",
                                             status="waiting_approval")
                    self._emit("approval_wait", {"step": "等待修改审批"})
                    decision = approval_cb(patch)
                    if decision is False or decision is None or (
                            isinstance(decision, dict)
                            and not decision.get("accepted", True)):
                        self.registry.finish_run(run_id, "cancelled", "用户拒绝 patch")
                        return {"ok": False, "cancelled": True, "run_id": run_id,
                                "patch": patch, "backups": backups}
                    self.registry.update_run(run_id, status="running")
                patch_diff = unified_diff(self.root, patch)[:3000]
                gate = authorize_agent_action(
                    self.trunk, "code_agent",
                    {"type": "edit_file", "risk": "high",
                     "args": {"path": ",".join(
                         f.get("path", "") for f in patch.get("files", []))},
                     "reason": patch.get("goal", "")},
                    title="代码 Agent 修改文件",
                    detail=patch_diff,
                    already_approved=bool(callable(approval_cb)))
                if not gate.get("allow"):
                    self.registry.finish_run(run_id, "failed", gate.get("reason", ""))
                    return {"ok": False, "run_id": run_id,
                            "error": gate.get("reason", "权限拒绝"),
                            "backups": backups}
                selected_files = None
                selected_hunks = None
                if isinstance(decision, dict):
                    selected_files = decision.get("selected_files") or None
                    selected_hunks = decision.get("selected_hunks") or None
                # 多文件批量修改先整体 dry-run：任何一处不合法都不落盘。
                dry = dry_run_patch(
                    self.root, patch, selected_files=selected_files,
                    selected_hunks=selected_hunks)
                self._emit("dry_run", {"step": "修改预演完成",
                                       "ok": dry.get("ok"),
                                       "files": dry.get("files") or [],
                                       "errors": dry.get("errors") or [],
                                       "progress": 0.5})
                if not dry.get("ok"):
                    err = "；".join(str(x) for x in (dry.get("errors") or []))
                    failed = _round_failed(
                        err + "\n提示：hunk.old 必须从文件内容原样复制（含缩进），"
                              "并保证在本文件中唯一。")
                    if failed:
                        return failed
                    last_error = (err + "\n提示：hunk.old 必须从文件内容原样复制"
                                        "（含缩进），并保证在本文件中唯一。")
                    continue
                # 预演/审批期间用户可能已经取消：落盘前最后确认一次，
                # 避免"点了停止但文件还是被改了"。
                self._check_control()
                applied = apply_patch(
                    self.root, patch, selected_files=selected_files,
                    selected_hunks=selected_hunks)
                backups.append(applied.get("backup_manifest") or "")
                self._last_backups.append(applied.get("backup_manifest"))
                applied_files = applied.get("applied") or []
                if not applied_files:
                    msg = ("patch 没有产生任何实际改动（hunk 的 new 与 old 相同，"
                           "或改动全部被取消选中）")
                    failed = _round_failed(msg)
                    if failed:
                        return failed
                    last_error = (msg + "\n请重新确认要改的片段，"
                                        "并给出与原文不同的 new 内容。")
                    continue
                previous_diff = patch_diff
                self._emit("applied", {
                    "step": "修改已应用",
                    "applied": applied_files,
                    "backup_manifest": applied.get("backup_manifest") or "",
                    "progress": 0.55})
                self.registry.update_run(run_id, current_step="运行测试",
                                         progress=0.6)
                self._emit("tests_start", {"step": "运行测试与 lint",
                                           "progress": 0.62})
                tests = self.run_tests()
                lint = self.run_lint()
                self._emit("tests", {"step": "测试完成",
                                     "ok": tests.get("ok"),
                                     "results": tests.get("results") or [],
                                     "progress": 0.82})
                self._emit("lint", {"step": "Lint 完成",
                                    "ok": lint.get("ok"),
                                    "results": lint.get("results") or []})
                verdict = evaluate_round(
                    round_no=round_no, max_rounds=max_rounds,
                    tests=tests, lint=lint,
                    fingerprint_history=fingerprints,
                    patch_history=patch_history,
                    patch_id=str(patch.get("patch_id") or ""))
                stop_reason = str(verdict.get("reason") or "max_rounds")
                self._emit("round_end", {
                    "step": "第 %d 轮：%s" % (round_no, verdict.get("message", "")),
                    "round": round_no, "max_rounds": max_rounds,
                    "reason": stop_reason, "stop": bool(verdict.get("stop")),
                    "progress": min(0.9, 0.7 + round_no * 0.02)})
                last_error = self._failure_digest(tests, lint)
                fingerprints.append(str(verdict.get("fingerprint") or ""))
                patch_history.append(str(patch.get("patch_id") or ""))
                if callable(checkpoint_cb):
                    try:
                        checkpoint_cb({
                            "round": round_no + 1, "max_rounds": max_rounds,
                            "last_error": last_error,
                            "last_diff": previous_diff,
                            "fingerprints": fingerprints,
                            "patches": patch_history,
                            "backups": list(backups),
                            "stop_reason": stop_reason,
                            "done": bool(verdict.get("stop")),
                        })
                    except Exception as e:  # 静默是故意的 - 断点保存失败不阻塞任务
                        _x6_swallowed(__name__, e, "save code agent checkpoint")
                if verdict.get("stop"):
                    if stop_reason == "tests_green":
                        self.registry.finish_run(run_id, "completed")
                        self._emit("done", {"step": "任务完成",
                                            "progress": 1.0,
                                            "stop_reason": stop_reason,
                                            "backups": backups})
                        return {"ok": True, "run_id": run_id, "patch": patch,
                                "applied": applied, "tests": tests,
                                "lint": lint, "backups": backups, "git": git,
                                "stop_reason": stop_reason,
                                "rounds_used": round_no,
                                "max_rounds": max_rounds}
                    self.registry.finish_run(run_id, "failed",
                                             str(verdict.get("message") or ""))
                    self._emit("failed", {"step": str(verdict.get("message") or ""),
                                          "error": last_error[:4000],
                                          "stop_reason": stop_reason,
                                          "progress": 1.0})
                    return {"ok": False, "run_id": run_id, "error": last_error,
                            "stop_reason": stop_reason, "rounds_used": round_no,
                            "max_rounds": max_rounds, "patch": patch,
                            "applied": applied, "tests": tests, "lint": lint,
                            "backups": backups, "git": git}
                self._emit("test_failed", {"step": "测试失败，准备回修",
                                           "output": last_error[:4000],
                                           "progress": 0.85})
            self.registry.finish_run(run_id, "failed", last_error)
            self._emit("failed", {"step": "达到最大回修轮数",
                                  "error": last_error[:4000], "progress": 1.0})
            return {"ok": False, "run_id": run_id, "error": last_error,
                    "stop_reason": stop_reason, "rounds_used": max_rounds,
                    "max_rounds": max_rounds, "tests": tests, "lint": lint,
                    "backups": backups, "git": git}
        except AgentCancelled:
            self.registry.finish_run(run_id, "cancelled", "用户取消")
            self._emit("cancelled", {"step": "任务已取消"})
            return {"ok": False, "cancelled": True, "run_id": run_id,
                    "error": "用户取消", "backups": backups}
        except Exception as e:
            env = normalize_error(e)
            self.registry.finish_run(run_id, "failed", env["technical_detail"])
            self._emit("failed", {"step": "任务失败",
                                  "error": env["message"], "progress": 1.0})
            return {"ok": False, "run_id": run_id, "error": env["message"],
                    "envelope": env, "backups": backups}

    @staticmethod
    def _failure_digest(tests, lint):
        """把测试/lint 失败压缩成给模型看的摘要：先列失败用例，再给尾部输出。

        原来是把各命令的完整输出直接拼起来（每条最多 16000 字符），
        进提示词时只截最后 6000 字符 —— 失败用例名经常正好被截掉。
        """
        parts = []
        for item in (tests or {}).get("results") or []:
            if item.get("ok") is True:
                continue
            names = []
            for f in item.get("failures") or []:
                label = str(f.get("file") or "")
                if f.get("test"):
                    label += "::" + str(f.get("test"))
                if f.get("line"):
                    label += ":L%s" % f.get("line")
                if label and label not in names:
                    names.append(label)
            block = "命令: %s" % item.get("command", "")
            if names:
                block += "\n失败用例: " + "、".join(names[:12])
            out = str(item.get("output") or "").strip()
            if out:
                block += "\n输出(尾部):\n" + out[-5000:]
            parts.append(block)
        for item in (lint or {}).get("results") or []:
            if item.get("ok") is True:
                continue
            out = str(item.get("output") or "").strip()
            if out:
                parts.append("lint: %s\n%s" % (item.get("command", ""),
                                               out[-2000:]))
        return "\n\n".join(parts)[-12000:]

    def rollback_all(self, backups):
        restored: list[str] = []
        for manifest in reversed(list(backups or [])):
            try:
                r = rollback(manifest)
                restored.extend(r.get("restored") or [])
            except Exception:  # 静默是故意的 - Agent 防御性回退，不阻塞主流程
                continue
        self._last_backups = []
        self._emit("rollback", {"step": "已撤销本次修改", "restored": restored})
        return {"ok": True, "restored": restored}

    def rollback_last(self):
        if not self._last_backups:
            return {"ok": False, "error": "没有可回滚的修改"}
        return self.rollback_all(list(self._last_backups))
