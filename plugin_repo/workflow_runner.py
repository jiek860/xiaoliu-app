# -*- coding: utf-8 -*-
"""P1-1: 轻量工作流 DSL（不做拖拽画布）

工作流文件格式：data/workflows/*.yaml
  name: 我的工作流
  steps:
    - name: 第一步
      action: llm          # llm / search / code / wait
      prompt: "分析这个问题"
    - name: 第二步
      action: search
      query: "补充资料"
    - name: 第三步
      action: llm
      prompt: "综合结果写报告"
"""
import os, json


class WorkflowRunner:
    def __init__(self, trunk):
        self.trunk = trunk
        self.base = getattr(trunk, "base", ".")
        self.workflow_dir = os.path.join(self.base, "data", "workflows")
        os.makedirs(self.workflow_dir, exist_ok=True)

    def list_workflows(self):
        """列出所有工作流"""
        out = []
        for f in os.listdir(self.workflow_dir):
            if f.endswith((".yaml", ".yml")):
                out.append(os.path.splitext(f)[0])
        return out

    def load(self, name):
        """加载工作流定义"""
        path = os.path.join(self.workflow_dir, name + ".yaml")
        if not os.path.exists(path):
            path = os.path.join(self.workflow_dir, name + ".yml")
        if not os.path.exists(path):
            return None
        try:
            import yaml
            return yaml.safe_load(open(path, encoding="utf-8"))
        except ImportError:
            # 没有 yaml 库，用简单解析
            return self._parse_simple(path)

    def _parse_simple(self, path):
        """简单 YAML 解析（没有 PyYAML 时用）"""
        steps = []
        current_step = {}
        for line in open(path, encoding="utf-8"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("  - name:"):
                if current_step:
                    steps.append(current_step)
                current_step = {"name": line.split(":", 1)[1].strip()}
            elif line.startswith("    action:"):
                current_step["action"] = line.split(":", 1)[1].strip()
            elif line.startswith("    prompt:"):
                current_step["prompt"] = line.split(":", 1)[1].strip()
            elif line.startswith("    query:"):
                current_step["query"] = line.split(":", 1)[1].strip()
        if current_step:
            steps.append(current_step)
        return {"steps": steps}

    def run(self, name, context=None):
        """跑工作流"""
        wf = self.load(name)
        if not wf or "steps" not in wf:
            return {"ok": False, "error": "工作流不存在"}
        context = context or {}
        results = []
        for step in wf["steps"]:
            action = step.get("action", "llm")
            result = self._run_step(action, step, context)
            results.append({"step": step.get("name", "?"), "result": result})
            context[step.get("name", "step")] = result
        return {"ok": True, "results": results, "context": context}

    def _run_step(self, action, step, context):
        """跑单步"""
        if action == "llm":
            llm = self.trunk.modules.get("llm") if self.trunk else None
            if llm:
                prompt = step.get("prompt", "")
                # 替换上下文变量
                for k, v in context.items():
                    prompt = prompt.replace("{" + k + "}", str(v))
                return llm.chat(prompt)
            return "（LLM 不可用）"
        elif action == "search":
            ds = self.trunk.modules.get("deep_search") if self.trunk else None
            if ds:
                return ds.search(step.get("query", ""))
            return {}
        elif action == "wait":
            import time
            time.sleep(float(step.get("seconds", 1)))
            return "done"
        return f"未知 action: {action}"