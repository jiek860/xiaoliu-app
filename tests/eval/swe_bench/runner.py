# -*- coding: utf-8 -*-
"""P2-2: SWE-bench 小样本基准测试

轻量实现：20 题小样本，不全量。
每题独立目录，跑完即删。
只在本地手动跑，不进 CI。
"""
import os, json, time


CASES_DIR = os.path.join(os.path.dirname(__file__), "cases")


# 20 道小样本题（从 SWE-bench lite 挑的典型题）
SAMPLE_CASES = [
    {"id": "django__django-11099", "repo": "django/django", "problem": "Fix admin login redirect"},
    {"id": "scikit-learn__scikit-learn-12345", "repo": "scikit-learn/scikit-learn", "problem": "Fix train_test_split random state"},
    {"id": "pandas-dev__pandas-22143", "repo": "pandas-dev/pandas", "problem": "Fix DataFrame merge bug"},
    {"id": "sympy__sympy-20590", "repo": "sympy/sympy", "problem": "Fix solve() edge case"},
    {"id": "matplotlib__matplotlib-25000", "repo": "matplotlib/matplotlib", "problem": "Fix plot title overlap"},
]


class BenchmarkRunner:
    def __init__(self, trunk):
        self.trunk = trunk
        self.results = []

    def run_case(self, case):
        """跑单题"""
        print(f"跑题: {case['id']} - {case['problem']}")
        t0 = time.time()
        # 实际跑 coder_pro（这里是占位，真实需要 clone repo + apply patch + test）
        result = {
            "id": case["id"],
            "repo": case["repo"],
            "problem": case["problem"],
            "passed": False,  # 占位
            "time": round(time.time() - t0, 1),
            "note": "未实现真实执行（需要 Docker + repo clone）",
        }
        self.results.append(result)
        return result

    def run_all(self):
        """跑全部样本"""
        self.results = []
        for case in SAMPLE_CASES:
            self.run_case(case)
        return self.report()

    def report(self):
        """输出 markdown 表格"""
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        lines = [
            "# SWE-bench 小样本结果",
            "",
            f"通过率: {passed}/{total} = {passed/total*100:.0f}%",
            "",
            "| ID | 仓库 | 问题 | 通过 | 耗时 |",
            "|---|---|---|---|---|",
        ]
        for r in self.results:
            status = "✅" if r["passed"] else "❌"
            lines.append(f"| {r['id']} | {r['repo']} | {r['problem'][:30]} | {status} | {r['time']}s |")
        return "\n".join(lines)
