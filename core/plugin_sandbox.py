# -*- coding: utf-8 -*-
"""P1-13: 插件沙箱 - 权限检查"""
import os, builtins


class PluginSandbox:
    """插件沙箱：限制插件能做什么"""
    def __init__(self, permissions=None):
        self.permissions = permissions or []

    def can_read_file(self):
        return "file_read" in self.permissions

    def can_write_file(self):
        return "file_write" in self.permissions

    def can_network(self):
        return "network" in self.permissions

    def can_run_code(self):
        return "code_run" in self.permissions

    def wrap_open(self):
        """包装open函数，检查权限"""
        orig_open = builtins.open
        sb = self
        def safe_open(path, mode="r", *a, **kw):
            if "w" in mode or "a" in mode:
                if not sb.can_write_file():
                    raise PermissionError("插件无写文件权限: " + str(path))
            else:
                if not sb.can_read_file():
                    raise PermissionError("插件无读文件权限: " + str(path))
            return orig_open(path, mode, *a, **kw)
        return safe_open

    def run(self, *a):
        return {
            "权限": self.permissions,
            "读文件": self.can_read_file(),
            "写文件": self.can_write_file(),
            "网络": self.can_network(),
        }
