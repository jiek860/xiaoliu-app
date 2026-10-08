# -*- coding: utf-8 -*-
"""P1-11: 工具调用记录与可视化"""
import os, json, time


class ToolCallLogger:
    """记录所有工具调用，供可视化展示"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.calls = []  # 最近50条

    def log_call(self, tool, args, result, elapsed=0.0):
        """记录一次工具调用"""
        self.calls.append({
            "tool": tool,
            "args": str(args)[:200],
            "result": str(result)[:200],
            "elapsed": round(elapsed, 2),
            "time": time.strftime("%H:%M:%S"),
        })
        if len(self.calls) > 50:
            self.calls = self.calls[-50:]

    def get_calls(self):
        return self.calls

    def run(self, *a):
        return {"调用数": len(self.calls), "最近": self.calls[-5:]}
