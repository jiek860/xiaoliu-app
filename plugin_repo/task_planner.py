# -*- coding: utf-8 -*-
"""
import os任务规划器 v10.0 - 真多步任务：LLM拆步+并行执行+子智能体委派+断点续做+质量评分"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from modules.base import BaseModule

class TaskPlanner(BaseModule):
    NAME = "task_planner"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.running = False
        self.tasks = {}  # {task_id: {goal, steps, results, status}}
        self.task_dir = os.path.join(self.base, r"data\tasks")
        os.makedirs(self.task_dir, exist_ok=True)
        self._load_tasks()

    def _load_tasks(self):
        """加载未完成任务（断点续做）"""
        try:
            for f in os.listdir(self.task_dir):
                if f.endswith(".json"):
                    d = json.load(open(os.path.join(self.task_dir, f), encoding="utf-8"))
                    if d.get("status") == "进行中":
                        self.tasks[d["id"]] = d
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _save_task(self, task):
        json.dump(task, open(os.path.join(self.task_dir, task["id"]+".json"), "w", encoding="utf-8"), ensure_ascii=False)

    def plan(self, goal):
        """v10: LLM拆步+标注依赖关系"""
        llm = self.trunk.modules.get("llm")
        if not llm: return [{"name":"分析","deps":[]},{"name":"执行","deps":["分析"]},{"name":"总结","deps":["执行"]}]
        prompt = f"""目标：{goal}
拆成3-5个步骤，格式：步骤名|依赖步骤名（逗号分隔）
每行一个，不要编号："""
        try:
            r = llm.chat(prompt)
            steps = []
            for l in r.split("\n"):
                l = l.strip()
                if not l: continue
                parts = l.split("|")
                name = parts[0].strip().strip("-•0123456789. ")
                deps = [d.strip() for d in parts[1].split(",")] if len(parts)>1 else []
                if 2 < len(name) < 40:
                    steps.append({"name": name, "deps": deps})
            return steps if steps else [{"name":"分析","deps":[]},{"name":"执行","deps":["分析"]},{"name":"总结","deps":["执行"]}]
        except:
            return [{"name":"分析","deps":[]},{"name":"执行","deps":["分析"]},{"name":"总结","deps":["执行"]}]

    def _route_step(self, step_name):
        """v10: 步骤自动路由到对应子智能体"""
        if any(k in step_name for k in ["代码","编程","写","bug","python","接口"]):
            return "agent_coder"
        if any(k in step_name for k in ["分析","总结","对比","评估","原因"]):
            return "agent_analyst"
        if any(k in step_name for k in ["规划","方案","计划","设计","创意"]):
            return "agent_planner"
        return None

    def _exec_step(self, step, context):
        """v10: 执行单步，优先调子智能体"""
        llm = self.trunk.modules.get("llm")
        agent_name = self._route_step(step["name"])
        if agent_name:
            try:
                self.trunk.call(agent_name, "__no__")  # 触发懒加载
                agent = self.trunk.modules.get(agent_name)
                if agent and hasattr(agent, "reply"):
                    return agent.reply(f"{step['name']}（背景：{context[:200]}）")
            except Exception as e:
                _x6_swallowed(__name__, e)
        # 兜底用LLM
        prompt = f"背景：{context}\n执行：{step['name']}\n结果："
        try: return llm.chat(prompt)
        except: return f"{step['name']}失败"

    def _score_result(self, step, result):
        """LLM 给结果打分，兼容 0-1 与 0-10 两种输出"""
        llm = self.trunk.modules.get("llm")
        if not llm or len(result) < 20:
            return 0.5
        try:
            r = (llm.chat(f"给这个结果打0-1分，只回一个数：{result[:200]}") or "").strip()
            import re
            m = re.search(r"(\d+(?:\.\d+)?)", r)
            if not m:
                return 0.6
            v = float(m.group(1))
            if v > 1:
                v = v / 10
            return max(0.0, min(1.0, v))
        except Exception:
            return 0.6

    def run_goal(self, goal, progress_cb=None):
        """v10: 真多步任务——拆步+并行+委派+评分+断点续做"""
        self.running = True
        task_id = "task_" + str(int(time.time()))
        steps = self.plan(goal)
        task = {"id": task_id, "goal": goal, "steps": steps, "results": {}, "status": "进行中"}
        self.tasks[task_id] = task
        self._save_task(task)

        # 拓扑排序执行
        done = set()
        results = {}
        while len(done) < len(steps) and self.running:
            # 找可并行的步骤
            ready = [s for s in steps if s["name"] not in done and all(d in done for d in s["deps"])]
            if not ready: break
            # 并行执行
            with ThreadPoolExecutor(max_workers=3) as ex:
                futures = {ex.submit(self._exec_step, s, str(results)): s for s in ready}
                for fut in as_completed(futures):
                    s = futures[fut]
                    try:
                        r = fut.result(timeout=60)
                    except:
                        r = f"{s['name']}超时"
                    score = self._score_result(s["name"], r)
                    results[s["name"]] = {"结果": r[:500], "分": score}
                    done.add(s["name"])
                    task["results"] = results
                    self._save_task(task)
                    if progress_cb:
                        progress_cb(f"{s['name']} 完成（分{score:.1f}）")

        # 汇总
        if progress_cb: progress_cb("汇总...")
        llm = self.trunk.modules.get("llm")
        try:
            final = llm.chat(f"目标：{goal}\n各步结果：{str(results)[:800]}\n总结：")
        except:
            final = "汇总失败"
        task["status"] = "完成"
        task["final"] = final
        self._save_task(task)
        self.running = False
        return final

    def list_tasks(self):
        return [{"id": t["id"], "goal": t["goal"], "status": t["status"]} for t in self.tasks.values()]

    def run(self, goal=""):
        if goal: return {"结果": self.run_goal(goal)}
        return {"进行中任务": len([t for t in self.tasks.values() if t["status"]=="进行中"]), "总任务": len(self.tasks)}

