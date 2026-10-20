# -*- coding: utf-8 -*-
"""代码 Agent Git 状态、快照、分支和提交。"""
from __future__ import annotations

import os
import re
import subprocess
import time
from core.agent_permissions import authorize_agent_action

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeGitToolsMixin:
    def git_status(self):
        st = self._run_argv(["git", "status", "--porcelain"], timeout=20)
        branch = self._run_argv(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=20)
        commit = self._run_argv(["git", "rev-parse", "HEAD"], timeout=20)
        return {
            "ok": bool(st.get("ok")),
            "dirty": bool((st.get("output") or "").strip()),
            "status": (st.get("output") or "")[:4000],
            "branch": (branch.get("output") or "").strip(),
            "commit": (commit.get("output") or "").strip(),
        }

    def git_protect(self):
        """记录 Git 状态；工作区有未提交修改时先另存完整 diff。"""
        info = self.git_status()
        if not info.get("ok"):
            return info
        if info.get("dirty"):
            try:
                r = self._run_argv(["git", "diff", "--binary"], timeout=30)
                bdir = os.path.join(self.root, "data", "patch_backups")
                os.makedirs(bdir, exist_ok=True)
                path = os.path.join(
                    bdir, "git_dirty_%s.patch" % time.strftime("%Y%m%d_%H%M%S"))
                with open(path, "w", encoding="utf-8") as f:
                    f.write(r.get("output") or "")
                info["dirty_backup"] = path
            except Exception as e:
                info["protect_error"] = str(e)[:200]
        return info

    def git_conflicts(self):
        """检测未解决的合并冲突标记。"""
        markers = []
        try:
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d not in
                               (".git", "__pycache__", "libs", "optional_libs",
                                "backups", "staging", "dist", "build", "data")]
                for name in filenames:
                    if not name.endswith((".py", ".js", ".ts", ".tsx", ".go",
                                          ".rs", ".java", ".md", ".json", ".yaml",
                                          ".yml")):
                        continue
                    p = os.path.join(dirpath, name)
                    try:
                        if os.path.getsize(p) > 2 * 1024 * 1024:
                            continue
                        txt = open(p, encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    if "<<<<<<< " in txt and ">>>>>>> " in txt:
                        markers.append(os.path.relpath(p, self.root).replace(chr(92), "/"))
        except Exception as e:  # 静默是故意的 - Git 冲突扫描仅做提示，扫描失败不阻塞代码任务
            _x6_swallowed(__name__, e, "best-effort fallback")
        return markers

    def git_snapshot(self):
        """创建不改工作区的 Git 快照（stash commit + 二进制 diff）。"""
        info = self.git_status()
        if not info.get("ok"):
            return info
        snapshot = {"ok": True, "branch": info.get("branch", ""),
                    "commit": info.get("commit", ""),
                    "dirty": info.get("dirty", False),
                    "conflicts": self.git_conflicts(),
                    "stash_commit": "", "diff_backup": ""}
        if info.get("dirty"):
            try:
                r = self._run_argv(
                    ["git", "stash", "create", "x6-agent-snapshot"], timeout=30)
                snapshot["stash_commit"] = (
                    r.get("output") or "").strip().splitlines()[-1:] or [""]
                if isinstance(snapshot["stash_commit"], list):
                    snapshot["stash_commit"] = snapshot["stash_commit"][0]
            except Exception as e:
                snapshot["stash_error"] = str(e)[:200]
            snapshot["diff_backup"] = self.git_protect().get("dirty_backup", "")
        return snapshot

    def git_create_work_branch(self, name=""):
        """显式创建 Agent 工作分支；不会自动调用。"""
        branch = name or ("x6-agent-" + time.strftime("%Y%m%d_%H%M%S"))
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$", branch):
            return {"ok": False, "error": "非法分支名"}
        if self.git_conflicts():
            return {"ok": False, "error": "工作区存在未解决冲突，拒绝切分支"}
        r = self._run_argv(["git", "switch", "-c", branch], timeout=30)
        return {"ok": r.get("ok"), "branch": branch,
                "output": r.get("output", ""), "exit_code": r.get("exit_code")}

    def git_commit_changes(self, message="x6 agent changes"):
        """显式提交当前修改；不会自动调用。"""
        msg = str(message or "x6 agent changes").replace("\x00", "")[:200]
        gate = authorize_agent_action(
            self.trunk, "code_agent",
            {"type": "shell", "risk": "high",
             "args": {"cmd": "git add -A && git commit -m <message>"},
             "reason": "提交 Agent 修改"},
            title="代码 Agent 请求提交 Git", detail=msg)
        if not gate.get("allow"):
            return {"ok": False, "error": gate.get("reason")}
        r1 = self._run_argv(["git", "add", "-A"], timeout=30)
        if not r1.get("ok"):
            return r1
        return self._run_argv(["git", "commit", "-m", msg], timeout=60)
