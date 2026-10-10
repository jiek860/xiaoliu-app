# -*- coding: utf-8 -*-
"""MCP客户端 v2.0 - 连接外部MCP服务器 + 调用工具 + 添加/删除/测试 + 历史 + 统计"""
import json, urllib.request, sys, os, time
from core.safe import safe
from modules.base import BaseModule


class MCPClient(BaseModule):
    NAME = "mcp_client"
    VERSION = "1.0"

    # 没有配置任何服务器时的兜底（保持旧行为）
    DEFAULT_SERVER = {"name": "桌面工具", "url": "http://localhost:3742"}

    def _log(self, msg):
        """BaseModule 没有 _log，这里补一个（stdio 传输层要回调它记日志）"""
        try:
            if self.trunk:
                self.trunk._log(msg)
                return
        except Exception:
            pass
        try:
            print(msg)
        except Exception:
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
            except Exception:
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
                         "command": cmd, "transport": "stdio"}
            elif url:
                entry = {"name": str(s.get("name") or url),
                         "url": url, "transport": "http"}
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
        for srv in self.servers:
            if srv.get("transport") == "stdio":
                self._connect_stdio(srv)
            else:
                self._connect_http(srv)
        return {"ok": True, "服务器数": len(self.servers), "工具数": len(self.tools),
                "失败": self.conn_errors}

    def _connect_http(self, srv):
        try:
            r = urllib.request.urlopen(srv["url"] + "/tools", timeout=3)
            data = json.loads(r.read().decode())
            if isinstance(data, list):
                for t in data:
                    if not isinstance(t, dict):
                        continue
                    t = dict(t)
                    t["_server"] = srv["name"]
                    t["_transport"] = "http"
                    self.tools.append(t)
        except Exception as e:
            self.conn_errors.append("%s (HTTP): %s" % (srv["name"], str(e)[:90]))

    def _connect_stdio(self, srv):
        """启动 stdio 子进程并拉工具列表"""
        try:
            from core.mcp_stdio import StdioMCPServer
        except Exception as e:
            self.conn_errors.append("%s (stdio): 传输层不可用 %s" % (srv["name"], str(e)[:60]))
            return
        # 兜底：同名槽位已经有连接就先收掉，别把它覆盖成孤儿
        old = self.stdio.pop(srv["name"], None)
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        s = StdioMCPServer(srv["name"], srv["command"], log=self._log)
        if s.start():
            # 竞态保护：如果这期间程序已经在退出了（stop() 已经跑过），
            # 这个刚起来的进程没人会再收，直接就地收掉，
            # 否则会留下一个孤儿 npx/node（实测能复现）。
            if self._stopped:
                try:
                    s.stop()
                except Exception:
                    pass
                return
            self.stdio[srv["name"]] = s
            self.tools.extend(s.tools)
            self._log("MCP stdio 已连接: %s（%d 个工具）" % (srv["name"], len(s.tools)))
        else:
            why = s.diagnostics()
            self.conn_errors.append("%s (stdio): %s" % (srv["name"], why))
            self._log("MCP stdio 连接失败: %s —— %s" % (srv["name"], why))
            try:
                s.stop()
            except Exception:
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
            except Exception:
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
        except Exception:
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
            r = urllib.request.urlopen(url + "/tools", timeout=3)
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
                req = urllib.request.Request(
                    srv["url"] + "/call", data=data,
                    headers={"Content-Type": "application/json"})
                r = urllib.request.urlopen(req, timeout=10)
                result = json.loads(r.read().decode())
                self._record(tool_name)
                return result
            except Exception as e:
                return {"错误": str(e)[:80]}
        return {"错误": "工具不存在: " + tool_name}

    def _record(self, tool_name):
        self.call_count += 1
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
                          "传输": t.get("_transport")} for t in self.tools]}

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

