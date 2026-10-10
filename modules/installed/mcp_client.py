# -*- coding: utf-8 -*-
"""MCP客户端 v2.0 - 连接外部MCP服务器 + 调用工具 + 添加/删除/测试 + 历史 + 统计"""
import json, urllib.request, sys, os
from core.safe import safe
from modules.base import BaseModule


class MCPClient(BaseModule):
    NAME = "mcp_client"
    VERSION = "1.0"

    # 没有配置任何服务器时的兜底（保持旧行为）
    DEFAULT_SERVER = {"name": "桌面工具", "url": "http://localhost:3742"}

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.servers = []
        self.tools = []
        self.history = []
        self.call_count = 0
        self.reload_servers()

    def reload_servers(self):
        """按 config["mcp_servers"] 重建服务器列表并重新拉取工具。

        gui/mcp_dialog.py 的增 / 删 / 重新连接三个按钮都是先写
        config["mcp_servers"]，再调本方法让客户端跟上。

        原来这个方法**根本不存在** —— 而对话框那边的调用被
        `try: mcp.reload_servers() except: pass` 静默吞掉，后果是：
        对话框里加过的服务器客户端从来不知道，拉工具列表始终只用
        __init__ 里写死的那个 localhost:3742（面板看着能用，实际没生效）。
        """
        cfg = []
        try:
            cfg = list((getattr(self.trunk, "config", None) or {}).get("mcp_servers", []) or [])
        except Exception:
            cfg = []
        servers = []
        for s in cfg:
            if not isinstance(s, dict):
                continue
            url = str(s.get("url") or "").strip()
            if not url or not s.get("enabled", True):
                continue
            servers.append({"name": str(s.get("name") or url), "url": url})
        if not servers:
            servers = [dict(self.DEFAULT_SERVER)]
        self.servers = servers
        self.tools = []
        self._connect()
        return {"ok": True, "服务器数": len(self.servers), "工具数": len(self.tools)}

    def _connect(self):
        """连接所有MCP服务器，拉取工具列表"""
        for srv in self.servers:
            try:
                r = urllib.request.urlopen(srv["url"] + "/tools", timeout=3)
                data = json.loads(r.read().decode())
                if isinstance(data, list):
                    for t in data:
                        t["_server"] = srv["name"]
                        self.tools.append(t)
            except: pass

    @safe
    def add_server(self, name, url):
        """添加MCP服务器"""
        self.servers.append({"name": name, "url": url})
        self._connect()
        return {"ok": True, "服务器数": len(self.servers)}

    @safe
    def remove_server(self, name):
        """删除MCP服务器"""
        before = len(self.servers)
        self.servers = [s for s in self.servers if s["name"] != name]
        return {"ok": len(self.servers) < before}

    @safe
    def test_server(self, url):
        """测试服务器是否能连接"""
        try:
            r = urllib.request.urlopen(url + "/tools", timeout=3)
            return {"ok": True, "状态": "可连接"}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:50]}

    @safe
    def call(self, tool_name, args=None):
        """调用MCP工具"""
        for t in self.tools:
            if t["name"] == tool_name:
                try:
                    url = None
                    for srv in self.servers:
                        if srv["name"] == t["_server"]:
                            url = srv["url"]
                            break
                    if not url: return {"错误": "找不到服务器"}
                    data = json.dumps({"tool": tool_name, "args": args or {}}).encode()
                    req = urllib.request.Request(url + "/call", data=data, headers={"Content-Type": "application/json"})
                    r = urllib.request.urlopen(req, timeout=10)
                    result = json.loads(r.read().decode())
                    # 记录历史
                    self.call_count += 1
                    self.history.append({"工具": tool_name, "时间": "now"})
                    if len(self.history) > 20:
                        self.history = self.history[-20:]
                    return result
                except Exception as e:
                    return {"错误": str(e)[:80]}
        return {"错误": "工具不存在: " + tool_name}

    def list_tools(self):
        return {"已连服务器": len(self.servers), "工具数": len(self.tools),
                "工具": [t["name"] for t in self.tools]}

    @safe
    def get_history(self, count=10):
        """获取调用历史"""
        return {"历史": self.history[-count:]}

    @safe
    def stats(self):
        """统计"""
        return {
            "服务器数": len(self.servers),
            "工具数": len(self.tools),
            "总调用次数": self.call_count
        }

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        return {"ok": True}

    def run(self, *args):
        return self.stats()

