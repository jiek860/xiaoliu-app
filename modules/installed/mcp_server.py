# -*- coding: utf-8 -*-
"""MCP服务 v2.0 - 工具注册 + 调用 + HTTP接口"""
import json, os, sys, threading
from core.safe import safe
from modules.base import BaseModule


class MCPServer(BaseModule):
    NAME = "mcp_server"
    VERSION = "1.0"
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "mcp_tools.json")
        self.tools = []
        self._register_tools()
        self._http_server = None
        self._http_thread = None

    _DEFAULTS = [
        {"name": "chat", "desc": "和AI聊天", "method": "llm.chat"},
        {"name": "search", "desc": "联网搜索", "method": "deep_search.search"},
        {"name": "run_code", "desc": "跑Python代码", "method": "code_runner.run"},
    ]

    def _register_tools(self):
        if os.path.exists(self.path):
            try:
                ext = json.load(open(self.path, encoding="utf-8"))
                if isinstance(ext, list):
                    merged = {t["name"]: t for t in self._DEFAULTS}
                    for t in ext:
                        if isinstance(t, dict) and t.get("name") and t.get("method"):
                            merged[t["name"]] = t
                    self.tools = list(merged.values())
                    return
            except: pass
        self.tools = [dict(t) for t in self._DEFAULTS]
        self._save()

    @safe
    def list_tools(self):
        """列出所有工具"""
        return {"工具数": len(self.tools), "工具": self.tools}

    @safe
    def add_tool(self, name, desc, method):
        """添加工具"""
        name = str(name).strip()
        if not name or not method:
            return {"ok": False, "原因": "name/method 必填"}
        t = {"name": name, "desc": str(desc)[:80], "method": str(method)}
        for i, x in enumerate(self.tools):
            if x["name"] == name:
                self.tools[i] = t
                break
        else:
            self.tools.append(t)
        self._save()
        return {"ok": True, "工具数": len(self.tools)}

    @safe
    def remove_tool(self, name):
        """删除工具"""
        before = len(self.tools)
        self.tools = [t for t in self.tools if t["name"] != name]
        if len(self.tools) == before:
            return {"ok": False, "原因": "工具不存在"}
        self._save()
        return {"ok": True, "工具数": len(self.tools)}

    def _save(self):
        try:
            json.dump(self.tools, open(self.path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except: pass

    @safe
    def call_tool(self, name, args=None):
        """调用工具"""
        for t in self.tools:
            if t["name"] == name:
                # MED-10: 判空，无点的方法名不崩
                m = t["method"]
                if "." in m:
                    mod, method = m.split(".", 1)
                else:
                    mod, method = m, "run"
                try:
                    if args is None:
                        r = self.trunk.call(mod, method)
                    elif isinstance(args, dict):
                        r = self.trunk.call(mod, method, **args)
                    else:
                        r = self.trunk.call(mod, method, args)
                    return {"工具": name, "结果": r}
                except Exception as e:
                    return {"错误": str(e)[:50]}
        return {"错误": "工具不存在"}

    @safe
    def start_http(self, port=8765):
        """启动HTTP接口"""
        if self._http_server:
            return {"状态": "已在运行"}
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler
            trunk = self.trunk
            class H(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path == "/tools":
                        import json as _j
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(_j.dumps({"工具": trunk.modules.get("mcp_server").tools}, ensure_ascii=False).encode())
                def log_message(self, *a): pass
            self._http_server = HTTPServer(("0.0.0.0", port), H)
            self._http_thread = threading.Thread(target=self._http_server.serve_forever, daemon=True)
            self._http_thread.start()
            return {"状态": "已启动", "端口": port}
        except Exception as e:
            return {"错误": str(e)[:80]}

    def run(self, *a):
        return self.list_tools()

