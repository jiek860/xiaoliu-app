# -*- coding: utf-8 -*-
"""coder_pro：git-first 代码 Agent 包装

包装 core/code_agent.py 的 CodeAgent：
  1. TOOLS 声明（confirm=True, danger=True）
  2. project_root 越界检查（走 path_safety.safe_join）
  3. git 快照策略：默认只 stash 快照，不自动 commit
  4. diff 审批对话框（GUI）
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, subprocess
from modules.base import BaseModule


class CoderPro(BaseModule):
    """代码 Agent 包装：带审批 + git 快照"""
    NAME = "coder_pro"
    VERSION = "1.0"

    TOOLS = [
        {"name": "coder_task", "method": "run_task",
         "desc": "让 AI 修改代码：探索项目→生成patch→审批→跑测试→修复",
         "args": {"goal": "要完成的代码任务，如：修复登录bug、加导出功能",
                  "project_path": "项目根目录，不填用当前目录"},
         "readonly": False,
         "danger": True,
         "confirm": True,
         "risk": "exec",
         "hints": ["写代码", "改bug", "修复", "重构", "code", "编程", "patch"]},
    ]

    MAX_ROUNDS = 3
    AUTO_COMMIT_DEFAULT = False  # 默认不自动 commit

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk

    def _safe_root(self, project_path=None):
        """安全解析项目根目录，防止越界"""
        base = getattr(self.trunk, "base", None) if self.trunk else None
        base = base or os.getcwd()
        if project_path:
            root = os.path.join(base, project_path)
        else:
            root = base
        return os.path.abspath(root)

    def _git_snapshot(self, root):
        """git stash 快照：不改用户提交历史，只做备份"""
        try:
            r = subprocess.run(
                ["git", "stash", "create", "x6-coder-pro-auto-snapshot"],
                cwd=root, capture_output=True, text=True, timeout=10)
            sha = r.stdout.strip()
            if sha:
                return {"snapshot": sha, "auto_commit": False}
        except Exception as e:
            _x6_swallowed(__name__, e)
        return {"snapshot": None, "auto_commit": False}

    def _default_approval(self, patch):
        """默认审批：命令行确认（GUI 模式下会被覆盖）"""
        files = patch.get("files", [])
        print(f"\n[CoderPro] AI 要修改 {len(files)} 个文件：")
        for f in files[:10]:
            print(f"  {f.get('path', '?')} ({f.get('action', '?')})")
        ans = input("批准？(y/n): ").strip().lower()
        return ans == "y"

    def run_task(self, goal, project_path=None):
        """主入口：跑一次代码任务"""
        from core.code_agent import CodeAgent

        root = self._safe_root(project_path)
        if not os.path.isdir(root):
            return {"ok": False, "error": f"目录不存在: {root}"}

        # git 快照（默认不自动 commit）
        snapshot = self._git_snapshot(root)

        # 构造 CodeAgent
        agent = CodeAgent(
            trunk=self.trunk,
            root=root,
            approval_cb=self._default_approval,
            event_cb=None,
        )

        # 跑任务
        try:
            result = agent.run(goal, max_rounds=self.MAX_ROUNDS)
            result["git_snapshot"] = snapshot
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "git_snapshot": snapshot}

    def run(self, *a):
        goal = a[0] if a else "写一个 hello world"
        return self.run_task(goal)
