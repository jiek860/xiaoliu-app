# -*- coding: utf-8 -*-
"""P1-12: 工具权限管理 - 每个工具单独授权 allow/ask/deny"""
import os, json


class ToolPermission:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "tool_permissions.json")
        self.perms = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        # 默认权限
        return {
            "deep_search": "allow",
            "code_runner": "ask",
            "computer_controller": "ask",
            "file_upload": "allow",
            "browser": "ask",
        }

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.perms, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def check(self, tool_name):
        """返回 allow/ask/deny"""
        return self.perms.get(tool_name, "allow")

    def set_perm(self, tool_name, level):
        """设置权限: allow/ask/deny"""
        self.perms[tool_name] = level
        self._save()

    def list_perms(self):
        return self.perms

    def run(self, *a):
        return {"工具数": len(self.perms), "权限": self.perms}
