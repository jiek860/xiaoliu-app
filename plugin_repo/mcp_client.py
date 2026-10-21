# -*- coding: utf-8 -*-
"""MCP客户端 v2.0 - 连接外部MCP服务器 + 调用工具 + 添加/删除/测试 + 历史 + 统计"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from core.safe_http import open_url as safe_open_url
import json, os, urllib.parse, urllib.request, time, threading
from core.safe import safe
from modules.base import BaseModule


class MCPClient(BaseModule):
    NAME = "mcp_client"
    VERSION = "1.0"

    # 没有配置任何服务器时的兜底（保持旧行为）
    DEFAULT_SERVER = {"name": "桌面工具", "url": "http://localhost:3742"}

    def _auth_headers(self, url=None, srv=None):
        """给 HTTP MCP 请求加鉴权头。

        内置 mcp_server 的 token 只存在内存里，同进程的 mcp_client
        直接读取，不落盘；外部服务器则使用配置里显式填写的 token。
        """
        token = ""
        try:
            if srv and srv.get("token"):
                token = str(srv.get("token") or "")
            if not token and url:
                u = str(url or "")
                host = ""
                try:
                    host = (urllib.parse.urlparse(u).hostname or "").lower()
                except Exception:
                    host = ""
                ms = self.trunk.modules.get("mcp_server") if self.trunk else None
                if ms is not None and host in ("127.0.0.1", "localhost", "::1"):
                    token = str(getattr(ms, "auth_token", "") or "")
        except Exception:
            token = ""
        return {"Authorization": "Bearer " + token} if token else {}

    def _log(self, msg):
        """BaseModule 没有 _log，这里补一个（stdio 传输层要回调它记日志）"""
        try:
            if self.trunk:
                self.trunk._log(msg)
                return
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        try:
            print(msg)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.trunk = trunk
        self.servers = []
        self.stdio = {}          # 服务器名 -> core.mcp_stdio.StdioMCPServer
        self.tools = []
        self.history = []
        self.call_count = 0
        self.conn_errors = []    # 连接失败的诊断，给界面看
        self._stopped = False    # 退出时置位，防止"正在连接的"在 stop 之后才落地
        self._lock = threading.RLock()   # 并行连接时保护 tools / stdio / conn_errors
        self._session_trusted = set()
        self.reload_servers()

    def reload_servers(self):
        """按 config["mcp_servers"] 重建服务器列表并重新连接。

        支持两种传输：
            {"name":..., "url": "http://localhost:3742"}                    HTTP
            {"name":..., "command": "npx -y @modelcontextprotocol/..."}     stdio

        gui/mcp_dialog.py 的增 / 删 / 勾选 / 重新连接都会调本方法。

        原来这个方法**不存在** —— 对话框那边的调用被 try/except 静默吞掉，
        后果是对话框里加过的服务器客户端从来不知道，拉工具列表始终只用
        __init__ 里写死的那个 localhost:3742。
        """
        self._stopped = False          # 显式重连视为"又开始工作了"
        # 先收掉旧的 stdio 子进程，不然每次重连都留一堆孤儿
        for s in list(self.stdio.values()):
            try:
                s.stop()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self.stdio = {}

        cfg = []
        try:
            cfg = list((getattr(self.trunk, "config", None) or {}).get("mcp_servers", []) or [])
        except Exception:
            cfg = []
        servers = []
        seen_names = set()
        for s in cfg:
            if not isinstance(s, dict) or not s.get("enabled", True):
                continue
            cmd = str(s.get("command") or "").strip()
            url = str(s.get("url") or "").strip()
            if cmd:
                entry = {"name": str(s.get("name") or cmd[:30]),
                         "command": cmd, "transport": "stdio",
                         "cwd": str(s.get("cwd") or ""),
                         "env": dict(s.get("env") or {}),
                         "risk": str(s.get("risk") or "")}
            elif url:
                entry = {"name": str(s.get("name") or url),
                         "url": url, "transport": "http",
                         "token": str(s.get("token") or "")}
            else:
                continue
            # 同名条目只留第一条：self.stdio 是按名字索引的，
            # 两个同名的 stdio 服务器会让后一个覆盖前一个的槽位，
            # 前一个子进程就再也没人管、变成孤儿了。
            if entry["name"] in seen_names:
                continue
            seen_names.add(entry["name"])
            servers.append(entry)
        # 兜底只在"从来没配过任何服务器"时生效。
        # 配置里明明有服务器、只是全被停用了，那就一个都不连 ——
        # 否则"全部取消勾选"会静默变回连默认那个，跟用户的意图相反
        # （测试里就撞到过：停用后回退去连内置的 3742，又冒出 4 个工具）。
        if not cfg:
            servers = [dict(self.DEFAULT_SERVER, transport="http")]

        self.servers = servers
        self.tools = []
        self.conn_errors = []
        self._connect_all()
        return {"ok": True, "服务器数": len(self.servers), "工具数": len(self.tools),
                "失败": self.conn_errors}

    def _connect_all(self):
        """并行连接所有服务器。

        原来是 for 循环串行连 —— 4 个 stdio 服务器（npx/uvx 起进程 + 握手）
        串起来要 6~10 秒，而这条路径会被 GUI 直接调用（打开 MCP 面板、
        点重连），整段时间 UI 是卡住的。并行之后只花最慢那一个的时间。
        """
        if not self.servers:
            return
        import concurrent.futures as cf
        # 预导入 stdio 传输层：4 个线程同时 import 同一个模块会在
        # importlib 锁上产生竞态，实测出现过 Windows 原生 access violation。
        try:
            import core.mcp_stdio  # noqa: F401
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        workers = max(1, min(8, len(self.servers)))
        try:
            with cf.ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(self._connect_one, self.servers))
        except Exception:
            for srv in self.servers:       # 并行出问题就退回串行，别整个失败
                self._connect_one(srv)

    def _connect_one(self, srv):
        if srv.get("transport") == "stdio":
            self._connect_stdio(srv)
        else:
            self._connect_http(srv)

    def _check_url(self, url, purpose="mcp_http"):
        try:
            from core.net_guard import get_net_guard
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            p = "local_mcp" if host in ("127.0.0.1", "localhost", "::1") else purpose
            d = get_net_guard(self.trunk).check(
                url, module="mcp_client", purpose=p)
            if not d.get("allow"):
                raise PermissionError(d.get("reason") or "网络请求被拒绝")
        except PermissionError:
            raise

    def _connect_http(self, srv):
        try:
            self._check_url(srv["url"] + "/tools")
            req = urllib.request.Request(
                srv["url"] + "/tools",
                headers=self._auth_headers(srv.get("url"), srv))
            r = safe_open_url(req, timeout=3)
            data = json.loads(r.read().decode())
            if isinstance(data, list):
                found = []
                for t in data:
                    if not isinstance(t, dict):
                        continue
                    t = dict(t)
                    t["_server"] = srv["name"]
                    t["_transport"] = "http"
                    from core.mcp_sandbox import classify_tool
                    t["_risk"] = classify_tool(t)
                    found.append(t)
                with self._lock:
                    self.tools.extend(found)
        except Exception as e:
            with self._lock:
                self.conn_errors.append("%s (HTTP): %s" % (srv["name"], str(e)[:90]))

    def _trust_path(self):
        base = getattr(self.trunk, "base", None) or "."
        # v2.1: 插件持久化必须落在 data/plugin_data/<插件名>/ 内
        new = os.path.join(base, "data", "plugin_data", "mcp_client", "mcp_trust.json")
        _legacy = os.path.join(base, "data", "security", "mcp_trust.json")
        if not os.path.exists(new) and os.path.exists(_legacy):
            try: os.replace(_legacy, new)
            except OSError:  # 静默是故意的：旧信任文件迁移失败不阻断主流程
                pass
        return new

    def _trusted_commands(self):
        try:
            data = json.load(open(self._trust_path(), encoding="utf-8"))
            return set(data.get("trusted_commands") or [])
        except Exception:
            return set()

    def _save_trusted_command(self, command_hash):
        try:
            path = self._trust_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            commands = self._trusted_commands()
            commands.add(str(command_hash))
            json.dump({"trusted_commands": sorted(commands)},
                      open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:  # 静默是故意的 - 信任写入失败不影响本次确认
            _x6_swallowed(__name__, e)

    def _confirm_startup(self, srv, cwd):
        cb = getattr(self.trunk, "confirm_cb", None)
        if not cb:
            return True
        try:
            from core.mcp_sandbox import startup_manifest
            m = startup_manifest(dict(srv, cwd=cwd))
            command_hash = m["command_sha256"]
            if command_hash in self._trusted_commands() or                     command_hash in self._session_trusted:
                return True
            detail = ("命令: %s\ncwd: %s\n环境变量: %s\n风险: %s" % (
                m["command"], m["cwd"], ",".join(m["env_keys"]) or "(最小白名单)",
                m["risk"]))
            scope_cb = getattr(self.trunk, "confirm_scope_cb", None)
            scope = scope_cb("启动 MCP 服务器 %s" % srv.get("name"), detail)                 if callable(scope_cb) else None
            if scope in ("once", "session", "always"):
                if scope == "always":
                    self._save_trusted_command(command_hash)
                elif scope == "session":
                    self._session_trusted.add(command_hash)
                self._audit({"subject": "mcp:trust:" + str(srv.get("name")),
                             "decision": "allow", "result": scope,
                             "reason": command_hash})
                return True
            if scope_cb:
                return False
            return bool(cb("启动 MCP 服务器 %s" % srv.get("name"), detail))
        except Exception:
            return False

    def _audit(self, event):
        try:
            from core.audit_log import AuditLog
            base = getattr(self.trunk, "base", None)
            if base:
                AuditLog(base).append(event)
        except Exception:  # 静默是故意的
            pass

    def _connect_stdio(self, srv):
        """启动 stdio 子进程并拉工具列表"""
        try:
            from core.mcp_stdio import StdioMCPServer
        except Exception as e:
            with self._lock:
                self.conn_errors.append("%s (stdio): 传输层不可用 %s"
                                        % (srv["name"], str(e)[:60]))
            return
        # 兜底：同名槽位已经有连接就先收掉，别把它覆盖成孤儿
        with self._lock:
            old = self.stdio.pop(srv["name"], None)
        if old is not None:
            try:
                old.stop()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        try:
            from core.child_process import sandbox_cwd
            base = getattr(self.trunk, "base", None) or "."
            cwd = sandbox_cwd(base, srv["name"], srv.get("cwd") or None)
        except Exception as e:
            with self._lock:
                self.conn_errors.append("%s (stdio): 工作目录被拒绝 %s"
                                        % (srv["name"], str(e)[:80]))
            return
        if not self._confirm_startup(srv, cwd):
            with self._lock:
                self.conn_errors.append("%s (stdio): 用户取消启动" % srv["name"])
            return
        s = StdioMCPServer(srv["name"], srv["command"], cwd=cwd,
                           log=self._log,
                           base=getattr(self.trunk, "base", None),
                           env_extra=srv.get("env") or {})
        if s.start():
            self._audit({"subject": "mcp:start:" + str(srv["name"]),
                         "decision": "allow", "result": "started",
                         "reason": "cwd=%s" % cwd})
            # 竞态保护：如果这期间程序已经在退出了（stop() 已经跑过），
            # 这个刚起来的进程没人会再收，直接就地收掉，
            # 否则会留下一个孤儿 npx/node（实测能复现）。
            if self._stopped:
                try:
                    s.stop()
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
                return
            from core.mcp_sandbox import classify_tool
            for tool in s.tools:
                tool["_risk"] = classify_tool(tool)
            with self._lock:
                self.stdio[srv["name"]] = s
                self.tools.extend(s.tools)
            self._log("MCP stdio 已连接: %s（%d 个工具）" % (srv["name"], len(s.tools)))
        else:
            why = s.diagnostics()
            with self._lock:
                self.conn_errors.append("%s (stdio): %s" % (srv["name"], why))
            self._log("MCP stdio 连接失败: %s —— %s" % (srv["name"], why))
            try:
                s.stop()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass

    def _connect(self):
        """兼容旧调用：等价于重连一次"""
        return self.reload_servers()

    def stop(self):
        """收掉所有 stdio 子进程（退出时调用，避免留下孤儿 npx/node）

        先置 _stopped，再收 —— 这样即使在收的过程中还有一条连接正在建立，
        它落地时也会自己发现并退出，不会变成没人管的孤儿进程。
        """
        self._stopped = True
        n = 0
        for s in list(self.stdio.values()):
            try:
                s.stop()
                n += 1
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self.stdio = {}
        self.tools = []
        return {"ok": True, "已收": n}

    @safe
    def add_stdio_server(self, name, command):
        """添加一个 stdio 型服务器（命令行）"""
        name = (name or "").strip()
        command = (command or "").strip()
        if not name or not command:
            return {"ok": False, "错误": "名称和命令都要填"}
        cfg = list((getattr(self.trunk, "config", None) or {}).get("mcp_servers", []) or [])
        cfg.append({"name": name, "command": command, "enabled": True})
        try:
            self.trunk.config["mcp_servers"] = cfg
            self.trunk.save_config()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return self.reload_servers()

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
            self._check_url(url + "/tools")
            req = urllib.request.Request(
                url + "/tools", headers=self._auth_headers(url))
            r = safe_open_url(req, timeout=3)
            return {"ok": True, "状态": "可连接"}
        except Exception as e:
            return {"ok": False, "错误": str(e)[:50]}

    @safe
    def call(self, tool_name, args=None):
        """调用 MCP 工具（按工具所属服务器自动选传输方式）"""
        for t in self.tools:
            if t.get("name") != tool_name:
                continue
            srv_name = t.get("_server")
            # ---- stdio 型 ----
            if t.get("_transport") == "stdio":
                s = self.stdio.get(srv_name)
                if not s:
                    return {"错误": "stdio 服务器未连接: %s" % srv_name}
                r = s.call_tool(tool_name, args)
                self._record(tool_name)
                if r.get("ok"):
                    return {"ok": True, "结果": r.get("结果", "")}
                return {"错误": r.get("错误") or r.get("结果") or "调用失败"}
            # ---- HTTP 型 ----
            try:
                srv = next((x for x in self.servers if x["name"] == srv_name), None)
                if not srv or not srv.get("url"):
                    return {"错误": "找不到服务器: %s" % srv_name}
                data = json.dumps({"tool": tool_name, "args": args or {}}).encode()
                self._check_url(srv["url"] + "/call")
                headers = {"Content-Type": "application/json"}
                headers.update(self._auth_headers(srv.get("url"), srv))
                req = urllib.request.Request(
                    srv["url"] + "/call", data=data, headers=headers)
                r = safe_open_url(req, timeout=10)
                result = json.loads(r.read().decode())
                self._record(tool_name)
                return result
            except Exception as e:
                return {"错误": str(e)[:80]}
        return {"错误": "工具不存在: " + tool_name}

    def _record(self, tool_name):
        self.call_count += 1
        self._audit({"subject": "mcp:tool:" + str(tool_name),
                     "decision": "allow", "result": "called"})
        self.history.append({"工具": tool_name,
                             "时间": time.strftime("%H:%M:%S")})
        if len(self.history) > 20:
            self.history = self.history[-20:]

    def list_tools(self):
        return {"已连服务器": len(self.servers),
                "已连工具": len(self.tools),
                "工具数": len(self.tools),
                "工具": [t.get("name") for t in self.tools],
                "明细": [{"名称": t.get("name"), "服务器": t.get("_server"),
                          "传输": t.get("_transport"),
                          "风险": (t.get("_risk") or {}).get("level", "unknown")}
                         for t in self.tools]}

    @safe
    def get_history(self, count=10):
        """获取调用历史"""
        return {"历史": self.history[-count:]}

    @safe
    def stats(self):
        """统计"""
        by_transport = {}
        for s in self.servers:
            k = s.get("transport", "http")
            by_transport[k] = by_transport.get(k, 0) + 1
        return {
            "服务器数": len(self.servers),
            "工具数": len(self.tools),
            "总调用次数": self.call_count,
            "按传输": by_transport,
            "stdio 进程数": len(self.stdio),
            "连接失败": self.conn_errors,
        }

    @safe
    def clear_history(self):
        """清空历史"""
        self.history = []
        return {"ok": True}

    def run(self, *args):
        return self.stats()

