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
    · 绑的是 0.0.0.0，本地工具服务没必要暴露到局域网 —— 改绑 127.0.0.1
    · start_http() 全项目没有任何地方调用，服务从来没起来过
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import hmac
import ipaddress
import json
import os
import secrets
import threading
import urllib.parse

from core.safe import safe
from modules.base import BaseModule


def _is_loopback_host(host):
    try:
        return ipaddress.ip_address(str(host or "").strip("[]")).is_loopback
    except ValueError:
        return str(host or "").strip().lower() == "localhost"


class MCPServer(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
    NAME = "mcp_server"
    VERSION = "1.0"

    DEFAULT_PORT = 3742

    # 注意：代码执行/电脑控制/文件写入绝不能出现在默认 HTTP 工具表里。
    # 用户如果确实要暴露自定义工具，必须自己在 data/mcp_tools.json 中添加，
    # 并在配置里显式开启 mcp_allow_dangerous_tools。
    _DEFAULTS = [
        {"name": "chat", "desc": "和AI聊天", "method": "llm.chat",
         "permissions": ["chat:read"]},
        {"name": "search", "desc": "联网搜索", "method": "deep_search.search",
         "permissions": ["network:read"]},
        {"name": "backup", "desc": "备份", "method": "backup.run",
         "permissions": ["filesystem:write"]},
    ]
    MAX_BODY = 64 * 1024

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
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        _sdir = os.path.join(self.base, "data", "plugin_data", "mcp_server")
        os.makedirs(_sdir, exist_ok=True)
        self.path = os.path.join(_sdir, "mcp_tools.json")
        _legacy = os.path.join(self.base, "data", "mcp_tools.json")
        if not os.path.exists(self.path) and os.path.exists(_legacy):
            try: os.replace(_legacy, self.path)
            except OSError:  # 静默是故意的：旧数据迁移失败不阻断主流程
                pass
        self.tools = []
        self._register_tools()
        self._http_server = None
        self._http_thread = None
        self.http_port = 0
        self.auth_token = secrets.token_urlsafe(32)
        self._bind_host = "127.0.0.1"

    # ------------------------------------------------------------ 工具登记

    def _dangerous_allowed(self):
        try:
            return bool((getattr(self.trunk, "config", {}) or {})
                        .get("mcp_allow_dangerous_tools", False))
        except Exception:
            return False

    def _filter_dangerous(self, tools):
        from core import security_policy
        if self._dangerous_allowed():
            return list(tools)
        return [t for t in tools
                if not security_policy.method_is_dangerous(t.get("method", ""))]

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
                    self.tools = self._filter_dangerous(merged.values())
                    return
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self.tools = self._filter_dangerous(
            [dict(t) for t in self._DEFAULTS])
        self._save()

    def _save(self):
        try:
            json.dump(self.tools, open(self.path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            _x6_swallowed(__name__, e)
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
        from core import security_policy
        if (security_policy.method_is_dangerous(method)
                and not self._dangerous_allowed()):
            return {"ok": False,
                    "原因": "危险工具默认禁止；如确需启用请设置 "
                            "mcp_allow_dangerous_tools=true"}
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
        from core import security_policy
        for t in self.tools:
            if t.get("name") != name:
                continue
            m = str(t.get("method") or "")
            if security_policy.method_is_dangerous(m):
                allow = False
                try:
                    allow = bool((getattr(self.trunk, "config", {}) or {})
                                 .get("mcp_allow_dangerous_tools", False))
                except Exception:
                    allow = False
                if not allow:
                    return {"ok": False, "工具": name,
                            "错误": "该工具会执行代码/写入文件/控制系统，"
                                    "HTTP 入口默认禁用；如确需启用请设置 "
                                    "mcp_allow_dangerous_tools=true"}
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
            method = str(t.get("method") or "")
            out.append({
                "name": name,
                "description": t.get("desc", "") or t.get("description", ""),
                "inputSchema": (t.get("inputSchema") or t.get("schema")
                                or self._SCHEMAS.get(name)
                                or {"type": "object", "additionalProperties": True}),
                "permissions": t.get("permissions") or (
                    [{"network": "read"}] if "search" in method else
                    [{"chat": "read"}] if method.startswith("llm.") else
                    [{"filesystem": "write"}] if "backup" in method else
                    [{"execute": "high"}]),
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

        if not _is_loopback_host(host):
            allowed_remote = bool((getattr(self.trunk, "config", {}) or {})
                                  .get("mcp_allow_remote", False))
            if not allowed_remote or not self.auth_token:
                return {"ok": False,
                        "错误": "非环回监听必须显式开启 mcp_allow_remote 并配置鉴权 token"}

        srv = self
        self._bind_host = host

        class Handler(BaseHTTPRequestHandler):
            server_version = "xiao6-mcp/3.0"
            protocol_version = "HTTP/1.1"

            def _host_ok(self):
                raw = (self.headers.get("Host") or "").strip().lower()
                if not raw:
                    return False
                if raw.startswith("["):
                    host = raw.split("]")[0].lstrip("[")
                else:
                    host = raw.rsplit(":", 1)[0] if ":" in raw else raw
                allowed = {"127.0.0.1", "localhost", "::1"}
                bind_host = str(getattr(srv, "_bind_host", "") or "").lower()
                if bind_host and _is_loopback_host(bind_host):
                    allowed.add(bind_host)
                return host in allowed

            def _origin_ok(self):
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                try:
                    p = urllib.parse.urlparse(origin)
                    return (p.scheme in ("http", "https")
                            and (p.hostname or "").lower() in
                            ("127.0.0.1", "localhost", "::1"))
                except Exception:
                    return False

            def _auth_ok(self):
                auth = self.headers.get("Authorization") or ""
                if not auth.startswith("Bearer "):
                    return False
                given = auth[len("Bearer "):].strip()
                return bool(given) and hmac.compare_digest(given, srv.auth_token)

            def _reject(self, code, msg):
                self._drain_body()
                self._send(code, {"ok": False, "错误": msg})

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
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

            def _content_length(self):
                raw = self.headers.get("Content-Length")
                if raw is None:
                    return 0
                if not str(raw).isdigit():
                    return -1
                return int(raw)

            def _drain_body(self):
                """把请求体读干净，避免残留数据污染复用连接上的下一个请求"""
                try:
                    n = self._content_length()
                    if n > 0 and n <= srv.MAX_BODY:
                        self.rfile.read(n)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

            def do_GET(self):
                if not self._host_ok() or not self._origin_ok():
                    self._send(403, {"ok": False, "错误": "来源不被允许"})
                    return
                if not self._auth_ok():
                    self._send(401, {"ok": False, "错误": "缺少或错误的访问令牌"})
                    return
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
                if not self._host_ok() or not self._origin_ok():
                    self._reject(403, "来源不被允许")
                    return
                if not self._auth_ok():
                    self._reject(401, "缺少或错误的访问令牌")
                    return
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._reject(415, "只接受 application/json")
                    return
                n = self._content_length()
                if n < 0 or n > srv.MAX_BODY:
                    self._reject(413, "请求体过大或 Content-Length 非法")
                    return
                p = (urlparse(self.path).path or "/").rstrip("/") or "/"
                if p != "/call":
                    self._drain_body()
                    self._send(404, {"ok": False, "错误": "未知路径: " + p})
                    return
                try:
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
        return {"状态": "已启动", "地址": "http://%s:%d" % (host, self.http_port),
                "工具数": len(self.tools),
                "鉴权": "Bearer token（同进程内由 mcp_client 自动携带）"}

    @safe
    def stop_http(self):
        """停掉本地工具服务"""
        if not self._http_server:
            return {"状态": "未运行"}
        try:
            self._http_server.shutdown()
            self._http_server.server_close()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        self._http_server = None
        self._http_thread = None
        self.http_port = 0
        self.auth_token = secrets.token_urlsafe(32)
        self._bind_host = "127.0.0.1"
        return {"状态": "已停止"}

    def stop(self):
        """统一释放入口（模块卸载/退出时调）。

        `stop_http` 是历史名字，很多地方已经在调；这里只做别名，
        让生命周期钩子（stop/close/shutdown）能统一找到它。
        """
        return self.stop_http()

    def status(self):
        return {"运行中": bool(self._http_server), "端口": self.http_port,
                "工具数": len(self.tools),
                "工具": [t.get("name") for t in self.tools]}

    def run(self, *a):
        return self.list_tools()
