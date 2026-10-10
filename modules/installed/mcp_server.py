# -*- coding: utf-8 -*-
"""MCP服务 v3.0 - 内嵌的本地工具服务

作用
----
把程序自己的几个能力（聊天 / 联网搜索 / 跑代码 / 备份）包成一层 HTTP 接口，
注册成 mcp_client 里的一个服务器。这样「本地工具」那条配置真的能连上 ——
不用再另外起什么外部进程。

接口约定（mcp_client 的 HTTP 分支就是这么调的）
    GET  /tools                          -> [{name, description, inputSchema}, ...]
    POST /call   {"tool": 名, "args": {}} -> {ok: true, 工具, 结果} / {ok: false, 错误}
    GET  /                               -> {ok, 名称, 工具数, 工具}   健康检查

v2.0 为什么从来没真正可用
------------------------
    · /tools 返回的是 {"工具": [...]} 这种**字典**，而客户端要的是**列表**
      （`if isinstance(data, list)`），于是永远拉到 0 个工具
    · 根本没有 /call，客户端 POST 过去只会收到 501
    · 默认端口 8765 和 mobile_remote 撞车（配置里期望的是 3742）
    · 绑的是 0.0.0.0，本地工具服务没必要暴露到局域网 —— 改绑 127.0.0.1
    · start_http() 全项目没有任何地方调用，服务从来没起来过
"""
import json
import os
import threading

from core.safe import safe
from modules.base import BaseModule


class MCPServer(BaseModule):
    NAME = "mcp_server"
    VERSION = "1.0"

    DEFAULT_PORT = 3742

    _DEFAULTS = [
        {"name": "chat", "desc": "和AI聊天", "method": "llm.chat"},
        {"name": "search", "desc": "联网搜索", "method": "deep_search.search"},
        {"name": "run_code", "desc": "跑Python代码", "method": "code_runner.run"},
        {"name": "backup", "desc": "备份", "method": "backup.run"},
    ]

    # 各工具的参数说明。args 是以关键字参数形式转给 trunk.call 的，
    # 这里写清楚客户端该传什么。没登记的工具给一个宽松的 schema。
    _SCHEMAS = {
        "chat": {"type": "object", "properties": {
            "message": {"type": "string", "description": "要对小6说的话"}},
            "required": ["message"]},
        "search": {"type": "object", "properties": {
            "query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"]},
        "run_code": {"type": "object", "properties": {
            "code": {"type": "string", "description": "要执行的 Python 代码"}},
            "required": ["code"]},
        "backup": {"type": "object", "properties": {}},
    }

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "mcp_tools.json")
        self.tools = []
        self._register_tools()
        self._http_server = None
        self._http_thread = None
        self.http_port = 0

    # ------------------------------------------------------------ 工具登记

    def _register_tools(self):
        if os.path.exists(self.path):
            try:
                ext = json.load(open(self.path, encoding="utf-8"))
                if isinstance(ext, list):
                    merged = {t["name"]: dict(t) for t in self._DEFAULTS
                              if isinstance(t, dict) and t.get("name")}
                    for t in ext:
                        if isinstance(t, dict) and t.get("name") and t.get("method"):
                            base = merged.get(t["name"], {})
                            merged[t["name"]] = {**base, **t}
                    self.tools = list(merged.values())
                    return
            except Exception:
                pass
        self.tools = [dict(t) for t in self._DEFAULTS]
        self._save()

    def _save(self):
        try:
            json.dump(self.tools, open(self.path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception:
            pass

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

    @safe
    def call_tool(self, name, args=None):
        """调用工具：把 "模块.方法" 交给 trunk.call，args 作为关键字参数"""
        for t in self.tools:
            if t.get("name") != name:
                continue
            m = str(t.get("method") or "")
            mod, method = (m.split(".", 1) if "." in m else (m, "run"))
            try:
                if args is None:
                    r = self.trunk.call(mod, method)
                elif isinstance(args, dict):
                    r = self.trunk.call(mod, method, **args)
                else:
                    r = self.trunk.call(mod, method, args)
                return {"ok": True, "工具": name, "结果": r}
            except Exception as e:
                return {"ok": False, "工具": name, "错误": str(e)[:120]}
        return {"ok": False, "错误": "工具不存在: %s" % name}

    # ------------------------------------------------------------ HTTP

    def _tools_payload(self):
        """按客户端期望的形状给出工具列表（必须是列表）"""
        out = []
        for t in self.tools:
            name = t.get("name", "")
            out.append({
                "name": name,
                "description": t.get("desc", "") or t.get("description", ""),
                "inputSchema": (t.get("inputSchema") or t.get("schema")
                                or self._SCHEMAS.get(name)
                                or {"type": "object", "additionalProperties": True}),
            })
        return out

    @safe
    def start_http(self, port=None, host="127.0.0.1"):
        """启动本地工具服务。重复调用是安全的（已在跑就直接返回）。"""
        if self._http_server:
            return {"状态": "已在运行", "端口": self.http_port}
        if port is None:
            try:
                port = int((getattr(self.trunk, "config", None) or {})
                           .get("mcp_server_port", self.DEFAULT_PORT))
            except Exception:
                port = self.DEFAULT_PORT

        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse

        srv = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "xiao6-mcp/3.0"
            protocol_version = "HTTP/1.1"

            def _send(self, code, obj):
                try:
                    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                except Exception:
                    body = b"{}"
                # 出错时直接关连接：错误分支可能没读请求体，
                # 在 HTTP/1.1 keep-alive 下残留的 body 会串到下一条请求上
                # （实测会让客户端报 ConnectionAbortedError）
                if code >= 400:
                    self.close_connection = True
                try:
                    self.send_response(code)
                    self.send_header("Content-Type",
                                     "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    if code >= 400:
                        self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    pass

            def _drain_body(self):
                """把请求体读干净，避免残留数据污染复用连接上的下一个请求"""
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > 0:
                        self.rfile.read(n)
                except Exception:
                    pass

            def do_GET(self):
                p = (urlparse(self.path).path or "/").rstrip("/") or "/"
                if p == "/tools":
                    self._send(200, srv._tools_payload())
                elif p == "/":
                    self._send(200, {
                        "ok": True, "名称": "小6本地工具",
                        "工具数": len(srv.tools),
                        "工具": [t.get("name") for t in srv.tools],
                    })
                else:
                    self._send(404, {"ok": False, "错误": "未知路径: " + p})

            def do_POST(self):
                p = (urlparse(self.path).path or "/").rstrip("/") or "/"
                if p != "/call":
                    self._drain_body()
                    self._send(404, {"ok": False, "错误": "未知路径: " + p})
                    return
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(n).decode("utf-8") if n else "{}"
                    payload = json.loads(raw or "{}")
                except Exception as e:
                    self._send(400, {"ok": False,
                                     "错误": "请求体不是合法 JSON: %s" % str(e)[:60]})
                    return
                if not isinstance(payload, dict):
                    self._send(400, {"ok": False, "错误": "请求体必须是 JSON 对象"})
                    return
                name = payload.get("tool") or payload.get("name") or ""
                args = payload.get("args")
                if args is None:
                    args = payload.get("arguments")
                try:
                    r = srv.call_tool(name, args)
                except Exception as e:
                    r = {"ok": False, "错误": str(e)[:120]}
                self._send(200, r if isinstance(r, dict) else {"ok": True, "结果": r})

            def log_message(self, *a):
                pass

        try:
            httpd = ThreadingHTTPServer((host, port), Handler)
            httpd.daemon_threads = True
        except Exception as e:
            return {"错误": "端口 %d 起不来: %s" % (port, str(e)[:80])}

        self._http_server = httpd
        # 记实际绑定的端口：传 0 时由系统分配，server_address 里才是真端口
        self.http_port = httpd.server_address[1]
        self._http_thread = threading.Thread(target=httpd.serve_forever, daemon=True,
                                             name="mcp-local-server")
        self._http_thread.start()
        return {"状态": "已启动", "地址": "http://%s:%d" % (host, port),
                "工具数": len(self.tools)}

    @safe
    def stop_http(self):
        """停掉本地工具服务"""
        if not self._http_server:
            return {"状态": "未运行"}
        try:
            self._http_server.shutdown()
            self._http_server.server_close()
        except Exception:
            pass
        self._http_server = None
        self._http_thread = None
        self.http_port = 0
        return {"状态": "已停止"}

    def status(self):
        return {"运行中": bool(self._http_server), "端口": self.http_port,
                "工具数": len(self.tools),
                "工具": [t.get("name") for t in self.tools]}

    def run(self, *a):
        return self.list_tools()
