# -*- coding: utf-8 -*-
"""P2-2: SWE-bench 小样本基准测试

轻量实现：5 道题小样本，不全量。
每题独立临时目录，跑完即删。
只在本地手动跑，不进 CI。

真实执行流程（完整版）：
1. git clone --depth 1 https://github.com/{repo}.git temp_dir
2. checkout 到对应的 commit
3. 调 coder_pro.run_task(problem)
4. 跑测试：python -m pytest tests/ -x
5. 测试过了 → passed = True
6. 删 temp_dir

现在是基础版：不真的 clone 和跑测试，只是模拟流程。
"""
import os, json, time, subprocess, shutil, shlex, sys


CASES_DIR = os.path.join(os.path.dirname(__file__), "cases")
TEMP_DIR = os.path.join(os.path.dirname(__file__), "_temp")


# 5 道小样本题（从 SWE-bench lite 挑的典型题）
# commit_hash: 题目对应的 base commit（跑题前要 checkout 到这里）
SAMPLE_CASES = [
    {"id": "django__django-11099", "repo": "django/django", "commit_hash": "",
     "test_cmd": "python -m pytest tests/ -x -q", "test_patch": "", "problem": "Fix admin login redirect"},
    {"id": "scikit-learn__scikit-learn-12345", "repo": "scikit-learn/scikit-learn", "commit_hash": "",
     "test_cmd": "python -m pytest tests/ -x -q", "test_patch": "", "problem": "Fix train_test_split random state"},
    {"id": "pandas-dev__pandas-22143", "repo": "pandas-dev/pandas", "commit_hash": "",
     "test_cmd": "python -m pytest tests/ -x -q", "test_patch": "", "problem": "Fix DataFrame merge bug"},
    {"id": "sympy__sympy-20590", "repo": "sympy/sympy", "commit_hash": "",
     "test_cmd": "python -m pytest tests/ -x -q", "test_patch": "", "problem": "Fix solve() edge case"},
    {"id": "matplotlib__matplotlib-25000", "repo": "matplotlib/matplotlib", "commit_hash": "",
     "test_cmd": "python -m pytest tests/ -x -q", "test_patch": "", "problem": "Fix plot title overlap"},
]


class BenchmarkRunner:
    def __init__(self, trunk, real_run=False):
        self.trunk = trunk
        self.results = []
        self.real_run = real_run  # True = 真的 clone repo 跑，False = 模拟

    def _clone_repo(self, repo_name, target_dir, commit_hash=""):
        """克隆仓库，可选 checkout 到指定 commit"""
        url = f"https://github.com/{repo_name}.git"
        try:
            # 先浅克隆
            subprocess.run(
                ["git", "clone", "--depth", "1", url, target_dir],
                capture_output=True, timeout=120)
            if not os.path.isdir(target_dir):
                return False

            # 如果有指定 commit，checkout 过去
            if commit_hash:
                # 要先 fetch 那个 commit（因为是浅克隆）
                subprocess.run(
                    ["git", "fetch", "--depth", "1", "origin", commit_hash],
                    cwd=target_dir, capture_output=True, timeout=120)
                subprocess.run(
                    ["git", "checkout", commit_hash],
                    cwd=target_dir, capture_output=True, timeout=30)

            return True
        except Exception:
            return False

    def run_case(self, case):
        """跑单题"""
        print(f"跑题: {case['id']} - {case['problem']}")
        t0 = time.time()
        temp_dir = os.path.join(TEMP_DIR, case["id"])

        passed = False
        status = "skipped"
        note = ""
        missing = [k for k in ("commit_hash", "test_cmd")
                   if not str(case.get(k) or "").strip()]
        if missing:
            note = "缺少评测数据: " + ", ".join(missing)
            result = {"id": case["id"], "repo": case["repo"],
                      "problem": case["problem"], "passed": False,
                      "status": status, "time": 0.0, "note": note}
            self.results.append(result)
            return result

        if self.real_run:
            # 真的执行
            try:
                os.makedirs(TEMP_DIR, exist_ok=True)
                # 1. clone repo（并 checkout 到题目对应的 commit）
                commit_hash = case.get("commit_hash", "")
                if not self._clone_repo(case["repo"], temp_dir, commit_hash):
                    note = "clone 或 checkout 失败"
                else:
                    patch = str(case.get("test_patch") or "")
                    if patch:
                        patch_file = os.path.join(temp_dir, ".x6_test.patch")
                        with open(patch_file, "w", encoding="utf-8") as f:
                            f.write(patch)
                        subprocess.run(["git", "apply", patch_file], cwd=temp_dir,
                                       capture_output=True, timeout=30)

                    # 2. 跑 coder_pro
                    coder = self.trunk.modules.get("coder_pro") if self.trunk else None
                    if coder and hasattr(coder, "run_task"):
                        try:
                            coder_result = coder.run_task(case["problem"], temp_dir, plan_mode=False)
                            note = "coder_pro 执行完成"
                        except Exception as e:
                            note = "coder_pro 失败: " + str(e)[:80]
                    else:
                        note = "coder_pro 未加载"

                    # 3. 跑测试
                    try:
                        cmd = shlex.split(str(case.get("test_cmd") or ""))
                        if cmd and cmd[0] in ("python", "python3"):
                            cmd[0] = sys.executable
                        test_result = subprocess.run(
                            cmd, cwd=temp_dir, capture_output=True, text=True,
                            timeout=120)
                        passed = (test_result.returncode == 0)
                        status = "passed" if passed else "failed"
                        note += " | 测试: " + ("通过" if passed else "失败")
                    except Exception as e:
                        note += " | 测试跑不了: " + str(e)[:60]
            finally:
                # 清理
                if os.path.isdir(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            # 模拟执行
            note = "模拟执行（real_run=False）"

        result = {
            "id": case["id"],
            "repo": case["repo"],
            "problem": case["problem"],
            "passed": passed,
            "status": status,
            "time": round(time.time() - t0, 1),
            "note": note,
        }
        self.results.append(result)
        return result

    def run_all(self, cases=None):
        """跑全部样本"""
        self.results = []
        cases = cases or SAMPLE_CASES
        for case in cases:
            self.run_case(case)
        return self.report()

    def report(self):
        """输出 markdown 表格"""
        passed = sum(1 for r in self.results if r["passed"])
        skipped = sum(1 for r in self.results if r.get("status") == "skipped")
        total = len(self.results)
        lines = [
            "# SWE-bench 小样本结果",
            "",
            f"通过率: {passed}/{total} = {passed/total*100:.0f}%"
            + ("（跳过 %d）" % skipped if skipped else "") if total > 0
            else "通过率: N/A",
            "",
            "| ID | 仓库 | 问题 | 通过 | 耗时 | 备注 |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.results:
            status = "✅" if r["passed"] else "❌"
            lines.append(
                f"| {r['id']} | {r['repo']} | {r['problem'][:30]} | {status} | {r['time']}s | {r['note'][:20]} |"
            )
        return "\n".join(lines)
