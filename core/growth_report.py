# -*- coding: utf-8 -*-
"""P1-09: 人格成长报告"""
import os, json, time
from datetime import datetime


class GrowthReport:
    """人格成长报告"""
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "personality.json")

    def report(self):
        """生成成长报告"""
        data = {}
        if os.path.exists(self.path):
            try:
                data = json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass

        birth = data.get("birth_time", time.time())
        days = int((time.time() - birth) / 86400)

        return {
            "认识天数": days,
            "关系阶段": data.get("relation_stage", 0),
            "性格特征": data.get("traits", {}),
            "里程碑": data.get("milestones", []),
            "记忆数": data.get("memory_count", 0),
        }

    def run(self, *a):
        return self.report()
