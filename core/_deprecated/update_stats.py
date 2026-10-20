# -*- coding: utf-8 -*-
"""更新统计上报 - 脱敏，只报版本和结果"""
import os
import json
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class UpdateStats:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(self.base, "data", "update_stats.json")
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e, "best-effort fallback")
        return {"checks": 0, "success": 0, "fail": 0}

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")

    def report_check(self):
        """上报：检查更新一次"""
        self.data["checks"] += 1
        self._save()

    def report_success(self):
        """上报：更新成功"""
        self.data["success"] += 1
        self._save()

    def report_fail(self):
        """上报：更新失败"""
        self.data["fail"] += 1
        self._save()

    def get_stats(self):
        return self.data

    def run(self):
        return self.get_stats()
