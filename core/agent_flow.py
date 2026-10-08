# -*- coding: utf-8 -*-
"""P1-06: Agent执行流程记录与可视化"""
import time


class AgentFlow:
    """记录任务执行步骤，供可视化"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.steps = []

    def record_step(self, name, status, detail=""):
        """记录一步执行"""
        self.steps.append({
            "name": name,
            "status": status,  # running/ok/fail
            "detail": str(detail)[:100],
            "time": time.strftime("%H:%M:%S"),
        })
        if len(self.steps) > 50:
            self.steps = self.steps[-50:]

    def get_flow(self):
        return self.steps

    def clear(self):
        self.steps = []

    def run(self, *a):
        return {"步骤数": len(self.steps), "最近": self.steps[-5:]}
