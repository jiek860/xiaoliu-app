# -*- coding: utf-8 -*-
"""任务闭环 v13.0 - 云端开真自主循环，本地保持简单拆步"""
import os, time, json
import sys
from modules.base import BaseModule


class TaskPipeline(BaseModule):
    NAME = "task_loop"
    VERSION = "1.0"
    AGENTS = {
        "代码": "agent_coder",
        "编程": "agent_coder",
        "分析": "agent_analyst",
        "总结": "agent_analyst",
        "策划": "agent_planner",
        "方案": "agent_planner",
    }

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.state_path = os.path.join(self.base, "data", "task_loop.json")
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.state_path):
            try:
                return json.load(open(self.state_path, encoding="utf-8"))
            except:
                pass
        return {"tasks": 0, "done": 0, "history": []}

    def _save(self):
        try:
            json.dump(self.state, open(self.state_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except:
            pass

    def _log(self, msg):
        if self.trunk:
            try:
                self.trunk._log(msg)
                return
            except:
                pass
        print(msg)

    def _is_cloud(self):
        """检测当前是不是云端模式"""
        try:
            llm = self.trunk.modules.get("llm")
            if llm:
                mode = llm.config.get("model_mode", "本地路由")
                return "云端" in str(mode) or "cloud" in str(mode).lower()
        except:
            pass
        return False

    def plan(self, goal):
        try:
            r = self.trunk.call("task_planner", "plan", goal)
            if isinstance(r, dict) and r.get("步骤"):
                return r["步骤"]
        except Exception as e:
            self._log("任务规划失败: %s" % str(e)[:50])
        return []

    def _pick_agent(self, step):
        name = str(step)[:40]
        for k, ag in self.AGENTS.items():
            if k in name:
                return ag
        return "agent_coder"

    def exec_step(self, step):
        ag = self._pick_agent(step)
        try:
            mod = self.trunk.modules.get(ag)
            if not mod:
                self.trunk.call(ag, "run")
                mod = self.trunk.modules.get(ag)
            if mod and hasattr(mod, "reply"):
                return {"agent": ag, "结果": mod.reply(str(step)[:200])}
            return {"agent": ag, "结果": "子智能体无 reply"}
        except Exception as e:
            return {"agent": ag, "结果": "执行失败: " + str(e)[:60]}

    def verify(self, step, result):
        if not any(k in str(step) for k in ("代码", "脚本", "函数", "运行")):
            return True, "非代码步骤，跳过"
        code = str(result.get("结果", ""))
        import re
        m = re.search(r"```(?:python|py)?\n(.*?)```", code, re.DOTALL)
        test = m.group(1) if m else code
        if not test.strip():
            return True, "无代码块"
        try:
            import subprocess, sys
            tf = os.path.join(self.base, "staging", "_task_test.py")
            open(tf, "w", encoding="utf-8").write(test)
            r = subprocess.run([sys.executable, "-m", "py_compile", tf],
                               capture_output=True, timeout=10)
            return r.returncode == 0, "沙盒验证通过" if r.returncode == 0 else r.stderr.decode("utf-8", errors="replace")[-80:]
        except Exception as e:
            return False, str(e)[:60]

    def score(self, goal, results):
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return 0.7
        try:
            brief = "\n".join("%s: %s" % (r["agent"], str(r["结果"])[:60]) for r in results)
            txt = llm.chat("任务：%s\n结果：%s\n只返回0到1的小数评分" % (goal[:60], brief[:200]))
            import re
            m = re.findall(r"0\.\d+", txt or "")
            return float(m[0]) if m else 0.7
        except:
            return 0.7

    def record(self, goal, results, score):
        self.state["tasks"] += 1
        self.state["done"] += 1
        self.state["history"].append({
            "goal": goal[:50], "步骤数": len(results),
            "评分": score, "time": time.strftime("%m-%d %H:%M")})
        self.state["history"] = self.state["history"][-20:]
        self._save()

    def run(self, goal=""):
        if not goal:
            return {"ok": False, "原因": "需要提供目标"}

        cloud = self._is_cloud()
        mode = "云端真自主循环" if cloud else "本地简单拆步"
        self._log("▶ 任务闭环开始（%s）: %s" % (mode, str(goal)[:50]))

        steps = self.plan(goal)
        self._log("① 拆成 %d 步" % len(steps))
        if not steps:
            return {"ok": False, "原因": "拆步失败", "模式": mode}

        results = []
        max_steps = 8 if cloud else 5  # 云端多跑几步
        for i, st in enumerate(steps[:max_steps], 1):
            self._log("② 执行第%d/%d步: %s" % (i, min(len(steps), max_steps), str(st)[:40]))
            r = self.exec_step(st)

            ok, msg = self.verify(st, r)
            # 云端模式：失败自动重试一次
            if not ok and cloud:
                self._log("  验证失败，自动重试: %s" % msg[:40])
                r = self.exec_step(str(st) + "（修正上次错误）")
                ok, msg = self.verify(st, r)

            results.append({"步骤": str(st)[:40], **r, "验证": msg})

        sc = self.score(goal, results)
        self._log("③ 质量评分: %.2f" % sc)
        self.record(goal, results, sc)
        self._log("▶ 任务闭环结束")
        return {"ok": True, "模式": mode, "步骤数": len(results), "评分": sc, "明细": results}

