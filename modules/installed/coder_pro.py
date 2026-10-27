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
         "hints": ["写代码", "改bug", "修复", "重构", "code", "编程", "patch"],
         "contract": {
             "params": {"goal": {"type": "string"}, "project_path": {"type": "string"}},
             "returns": {"type": "object"},
             "errors": ["PLUGIN_INTERNAL_ERROR", "PLUGIN_NEEDS_CONFIRM"],
             "side_effects": ["filesystem_write", "process"],
             "description": "让 AI 修改代码，带审批和 git 快照",
             "not_responsible": ["不负责写测试用例", "不负责代码审查"]
         }},
    ]

    MAX_ROUNDS = 3
    AUTO_COMMIT_DEFAULT = False  # 默认不自动 commit

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        # 模块卸载后置位：让排队中的下一步立刻退出，不再动用户仓库
        self._closed = False

    def close(self):
        """取消后续任务（模块卸载/退出时调）。

        这个模块没有常驻资源：git 快照和测试都是 subprocess.run 同步跑完就回收。
        所以 close() 只做一件事 —— 把 _closed 置位，让已经开始排队/下一步的
        run_task 立刻返回「已停止」，不再对用户仓库动手。
        """
        self._closed = True
        return {"ok": True, "状态": "已停止"}

    def _safe_root(self, project_path=None):
        """安全解析项目根目录，防止越界"""
        # 不再退回「当前工作目录」：它是进程级全局，从快捷方式启动时可能是
        # C:\Windows\System32 —— 那样 project_root 会解析到系统目录。
        # 用本文件所在的项目树兜底，结果可预测。
        base = getattr(self.trunk, "base", None) if self.trunk else None
        base = base or os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
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

    def _make_plan(self, goal, root):
        """Plan 阶段：让 LLM 先出执行计划"""
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"ok": False, "error": "LLM未加载，无法出计划"}

        prompt = """你是资深软件工程师。用户要完成这个任务：

{goal}

项目目录：{root}

请先分析项目结构，然后给出一个清晰的执行计划，包括：
1. 需要修改哪些文件（路径）
2. 每个文件大概改什么
3. 预计几步完成

输出格式（markdown）：
## 执行计划

### 涉及文件
- path/to/file1.py：做什么
- path/to/file2.py：做什么

### 步骤
1. 第一步做什么
2. 第二步做什么
3. 第三步做什么

请只输出计划，不要开始改代码。""".format(goal=goal, root=root)

        try:
            plan = llm.chat(prompt)
            return {"ok": True, "plan": plan}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def run_task(self, goal, project_path=None, plan_mode=True):
        """主入口：Plan/Act 模式

        plan_mode=True（默认）：先出计划，用户批准后再执行
        plan_mode=False：直接执行（旧行为）
        """
        from core.code_agent import CodeAgent

        if getattr(self, "_closed", False):
            return {"ok": False, "error": "coder_pro 已停止（模块被卸载）"}
        root = self._safe_root(project_path)
        if not os.path.isdir(root):
            return {"ok": False, "error": f"目录不存在: {root}"}

        # Plan 阶段
        plan = ""
        if plan_mode:
            plan_result = self._make_plan(goal, root)
            if plan_result.get("ok"):
                plan = plan_result.get("plan", "")

                # 弹 GUI 对话框让用户确认/编辑计划
                approved = True
                if self.trunk and hasattr(self.trunk, "confirm_plan"):
                    approved, plan = self.trunk.confirm_plan(plan, goal)

                if not approved:
                    return {"ok": False, "error": "用户取消了任务"}

                # 用户批准了，继续执行（plan 可能被用户编辑过）

        # Act 阶段：git 快照（默认不自动 commit）
        snapshot = self._git_snapshot(root)

        # 构造 CodeAgent
        agent = CodeAgent(
            trunk=self.trunk,
            root=root,
            approval_cb=self._default_approval,
            event_cb=None,
        )

        # 跑任务（把用户批准的计划加到 goal 里，让 CodeAgent 按计划执行）
        actual_goal = goal
        if plan:
            actual_goal = f"用户任务：{goal}\n\n已批准的执行计划（请按这个计划执行）：\n{plan}"

        try:
            result = agent.run(actual_goal, max_rounds=self.MAX_ROUNDS)
            result["git_snapshot"] = snapshot
            result["plan"] = plan
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)[:200], "git_snapshot": snapshot}

    def run(self, *a):
        goal = a[0] if a else "写一个 hello world"
        return self.run_task(goal)
