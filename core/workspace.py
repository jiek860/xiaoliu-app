# -*- coding: utf-8 -*-
"""工作区隔离：每个工作区有独立的目录和数据命名空间。"""
import os
import re

from core.path_safety import safe_name


class Workspace:
    def __init__(self, trunk=None, workspace_id="default"):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.id = safe_name(workspace_id, default="default", max_len=40)
        self.root = os.path.join(self.base, "data", "workspaces", self.id)
        os.makedirs(self.root, exist_ok=True)

    def path(self, *parts):
        p = self.root
        for x in parts:
            p = os.path.join(p, safe_name(x, default="file", max_len=120))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def data_dir(self):
        d = os.path.join(self.root, "data")
        os.makedirs(d, exist_ok=True)
        return d

    def knowledge_dir(self):
        d = os.path.join(self.root, "knowledge")
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def valid_id(value):
        return bool(re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}",
                                 str(value or "")))
