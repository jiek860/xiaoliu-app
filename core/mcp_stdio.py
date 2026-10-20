# -*- coding: utf-8 -*-
r"""MCP stdio 传输 —— 让程序能连上那些"用命令行启动"的 MCP 服务器

背景
----
MCP 服务器有两种常见传输方式：

  · HTTP（也叫 SSE/streamable-http）：客户端去请求 <地址>/tools
    本地那个 3742 端口的小工具服务就是这种。

  · stdio：客户端把服务器当成子进程启动（npx / uvx / python ...），
    双方用标准输入输出交换 JSON-RPC 2.0 消息，一行一条。
    官方那几个（filesystem / fetch / git / sqlite）全是这种。

mcp_client 原来只支持 HTTP，所以官方那些一个都用不上。本模块补上 stdio。

协议要点（stdio 传输）
----------------------
  1. 启动子进程，消息是 **一行一个 JSON 对象**（newline-delimited JSON-RPC 2.0）
  2. 握手：
       客户端 -> initialize            {protocolVersion, capabilities, clientInfo}
       服务端 -> {result: {protocolVersion, capabilities, serverInfo}}
       客户端 -> notifications/initialized   （通知，无 id，不需要回复）
  3. 列工具：tools/list            -> {result: {tools: [{name, description, inputSchema}]}}
  4. 调工具：tools/call {name, arguments} -> {result: {content: [...], isError?}}

其他实现细节
------------
  · Windows 上 npx / uvx 是 .cmd 批处理，CreateProcess 不能直接执行，
    必须交给 cmd.exe /c；同时加 CREATE_NO_WINDOW 免得弹黑框。
  · stdout 上可能有非 JSON 的横幅/日志，解析失败就丢进诊断尾巴，不当成错误。
  · stderr 单独开线程抽干（不抽干的话管道写满会把子进程卡死），
    只保留最后若干行，握手失败时用来告诉用户"到底为什么连不上"。
  · 请求按 id 关联，靠 Event 等待；超时会把自己从待办表里摘掉，避免泄漏。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import atexit
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from core import command_policy
from core.child_process import minimal_child_env
from core.windows_job import WindowsJob

from core.agent_harness import get_run_registry

# 官方当前常用的协议版本；服务端会回它自己支持的版本，我们跟着用即可
PROTOCOL_VERSION = "2024-11-05"

# 活着的连接。程序退出时兜底收掉子进程 ——
# 不然 npx / node 那些会变成孤儿进程一直挂在后台。
_LIVE = set()
_LIVE_LOCK = threading.Lock()


def _cleanup_all():
    with _LIVE_LOCK:
        items = list(_LIVE)
    for s in items:
        try:
            s.stop()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass


atexit.register(_cleanup_all)


def live_count():
    with _LIVE_LOCK:
        return len(_LIVE)


def _child_env(extra=None):
    """给子进程准备环境变量：把常见的可执行文件目录补进 PATH。

    为什么需要：MCP 服务器大多靠 npx / uvx 启动，而这两个不一定在 PATH 上 ——
    `pip install uv` 装的 uv/uvx 落在 Python 的 Scripts 目录里，
    该目录默认**不在** PATH 上；官方安装器装的 uv 在 ~/.local/bin；
    node 装在 C:\\Program Files\\nodejs。用户（尤其是朋友）在自己终端里
    未必配过这些，程序这边补上就不用他们自己折腾环境变量了。
    """
    env = minimal_child_env(dict(extra or {}, X6_MCP_SANDBOX="1"))
    # Keep npx/uvx discoverable without inheriting the parent's full environment.
    extra = [
        os.path.join(sys.prefix, "Scripts"),
        os.path.join(sys.prefix, "bin"),
        os.path.join(os.path.expanduser("~"), ".local", "bin"),
        os.path.join(os.path.expanduser("~"), ".cargo", "bin"),
    ]
    if os.name == "nt":
        extra += [
            os.path.join(os.environ.get("APPDATA", ""), "npm"),
            r"C:\Program Files\nodejs",
            r"C:\Program Files (x86)\nodejs",
        ]
    exist = [d for d in extra if d and os.path.isdir(d)]
    if exist:
        env["PATH"] = os.pathsep.join(exist + [env.get("PATH", "")])
    return env


class StdioMCPServer:
    """一个 stdio 型 MCP 服务器的连接"""

    def __init__(self, name, command, cwd=None, timeout=25, log=None,
                 base=None, max_memory_mb=1024, max_cpu_seconds=0,
                 max_processes=8, max_line_bytes=1024 * 1024,
                 max_total_bytes=8 * 1024 * 1024,
                 max_stderr_bytes=512 * 1024, env_extra=None):
        self.name = name
        self.command = (command or "").strip()
        self.cwd = cwd
        self.base = base
        self.env_extra = dict(env_extra or {})
        self.timeout = timeout
        self._log = log or (lambda m: None)

        self.proc = None
        self.tools = []
        self.server_info = {}
        self.protocol_version = ""
        self.last_error = ""

        self._id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._stderr_tail = deque(maxlen=15)

        self._reader = None
        self._err_reader = None
        self._monitor = None
        self._job = None
        self.max_memory_mb = int(max_memory_mb or 0)
        self.max_cpu_seconds = int(max_cpu_seconds or 0)
        self.max_processes = int(max_processes or 0)
        self.max_line_bytes = int(max_line_bytes or 0)
        self.max_total_bytes = int(max_total_bytes or 0)
        self.max_stderr_bytes = int(max_stderr_bytes or 0)
        self._stdout_bytes = 0
        self._stderr_bytes = 0
        self.limit_error = ""
        self._alive = False
        self._run_id = ""

    # ------------------------------------------------------------ 生命周期

    def _popen_args(self):
        """返回 (Popen 的第一个参数, 是否 shell)

        Windows 上 npx / uvx / npm 都是 .cmd 批处理，CreateProcess 起不来，
        必须经 cmd.exe。怎么经，实测踩过一轮坑：

            ["cmd.exe", "/c", 原样命令]            无空格时可用，带引号就废
            ["cmd.exe", "/c", '"' + 命令 + '"']    也不可用
            显式 cmd.exe + shell=False 命令行串     可用（带空格带引号都行）

        原因是列表形式会被 list2cmdline 处理，把用户写的内部引号转义成 \\" ，
        cmd 认不出来；而 shell=True 是把整条命令串原样交给
        `cmd.exe /c "<整条命令>"`，cmd 按自己的规则去掉最外层那一对引号，
        用户写的内部引号原样保留。用户填的本来就是一条命令行，这样最贴预期。
        """
        # 先做引号外元字符检查；需要 cmd 包装的命令使用显式 cmd.exe，
        # 但 Popen 始终 shell=False。
        ok, reason, _token = command_policy.check_command(self.command)
        if not ok:
            raise ValueError("MCP 命令不符合执行策略: " + reason)
        args, _used_shell_wrapper = command_policy.build_exec_argv(self.command)
        # 第二项保留为兼容返回值；Popen 始终 shell=False。
        return args, False

    def start(self):
        """启动子进程并完成 MCP 握手。成功返回 True。"""
        try:
            self._run_id = "mcp:%s:%s" % (
                self.name, int(time.time() * 1000))
            get_run_registry().start_run(
                "mcp", "MCP: %s" % self.name, run_id=self._run_id,
                status="running", metadata={"command": self.command[:200]})
        except Exception:  # 静默是故意的
            self._run_id = ""
        if not self.command:
            self.last_error = "命令为空"
            self._finish_run("failed", self.last_error)
            return False
        try:
            argv, _used_shell = self._popen_args()
            kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          errors="replace", bufsize=1, cwd=self.cwd,
                          shell=False, env=_child_env(self.env_extra))
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(argv, **kwargs)
            if os.name == "nt":
                self._job = WindowsJob(
                    max_memory_mb=self.max_memory_mb,
                    max_cpu_seconds=self.max_cpu_seconds,
                    max_processes=self.max_processes,
                    kill_on_close=True)
                attach = self._job.attach(self.proc.pid)
                if not attach.get("ok"):
                    self.last_error = "Job Object 未附加: %s" % attach.get("error")
        except Exception as e:
            self.last_error = "启动失败: %s" % str(e)[:120]
            self._finish_run("failed", self.last_error)
            return False

        self._alive = True
        with _LIVE_LOCK:
            _LIVE.add(self)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True,
                                        name="mcp-stdio-%s" % self.name)
        self._reader.start()
        self._err_reader = threading.Thread(target=self._drain_stderr, daemon=True,
                                            name="mcp-stderr-%s" % self.name)
        self._err_reader.start()
        self._monitor = threading.Thread(target=self._monitor_resources,
                                         daemon=True,
                                         name="mcp-monitor-%s" % self.name)
        self._monitor.start()

        try:
            r = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "xiao6", "version": "1.0"},
            })
            if isinstance(r, dict):
                self.protocol_version = str(r.get("protocolVersion") or "")
                self.server_info = r.get("serverInfo") or {}
            # 握手第三步：通知，不需要回复
            self._notify("notifications/initialized", {})
        except Exception as e:
            if self.limit_error:
                self.last_error = self.limit_error
            else:
                self.last_error = "握手失败: %s" % str(e)[:120]
            self.stop()
            return False

        tools = self.list_tools()
        if tools is None:
            self.last_error = "拉取工具列表失败: %s" % (self.last_error or "未知")
            self._finish_run("failed", self.last_error)
            return False
        try:
            get_run_registry().update_run(
                self._run_id, status="background",
                current_step="已连接（%d 个工具）" % len(tools or []),
                progress=1.0, metadata={
                    "command": self.command[:200],
                    "tools": len(tools or []),
                    "pid": getattr(self.proc, "pid", 0),
                })
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return True

    def _finish_run(self, status, error=""):
        if not getattr(self, "_run_id", ""):
            return
        try:
            get_run_registry().finish_run(self._run_id, status, error)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _monitor_resources(self):
        try:
            import psutil
            p = psutil.Process(self.proc.pid)
        except Exception:  # 静默是故意的 - psutil 缺失时不做资源监控
            return
        while self._alive and self.proc and self.proc.poll() is None:
            try:
                if p.memory_info().rss > self.max_memory_mb * 1024 * 1024:
                    self.last_error = "MCP 子进程超过内存上限 %dMB，已终止" % self.max_memory_mb
                    self.stop()
                    return
            except Exception:  # 静默是故意的 - 进程已退出或权限变化
                return
            time.sleep(1)

    def alive(self):
        return bool(self._alive and self.proc and self.proc.poll() is None)

    def stop(self):
        self._alive = False
        self._finish_run("completed", self.last_error if not self.proc else "")
        with _LIVE_LOCK:
            _LIVE.discard(self)
        p = self.proc
        if not p:
            return
        if self._job is not None:
            try:
                self._job.terminate()
            except Exception:  # 静默是故意的
                pass
            try:
                self._job.close()
            except Exception:  # 静默是故意的
                pass
            self._job = None
        try:
            if p.stdin:
                p.stdin.close()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        # Windows 上进程是经 shell 起的，terminate() 只杀掉 cmd.exe，
        # 真正干活的子进程（npx -> node）会变成孤儿。用 taskkill /T 连整棵树一起收。
        if os.name == "nt" and p.pid:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        self.proc = None

    # ------------------------------------------------------------ 收发

    def _write(self, payload):
        if not self.alive():
            raise RuntimeError("子进程未运行")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            self.proc.stdin.write(line)
            self.proc.stdin.flush()

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def _request(self, method, params=None, timeout=None):
        if not self.alive():
            raise RuntimeError("子进程未运行")
        timeout = timeout if timeout is not None else self.timeout
        with self._lock:
            self._id += 1
            rid = self._id
            slot = {"event": threading.Event()}
            self._pending[rid] = slot
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._write(msg)
        except Exception:
            with self._lock:
                self._pending.pop(rid, None)
            raise
        if not slot["event"].wait(timeout):
            with self._lock:
                self._pending.pop(rid, None)
            raise TimeoutError("%s 超时(%ss)" % (method, timeout))
        if "error" in slot:
            e = slot["error"]
            raise RuntimeError(str(e.get("message") or e)[:160]
                               if isinstance(e, dict) else str(e)[:160])
        return slot.get("result")

    def _limit_triggered(self, message):
        self.limit_error = message
        self.last_error = message
        self._stderr_tail.append(message[:180])
        try:
            self.stop()
        except Exception:  # 静默是故意的
            pass

    def _read_stdout(self):
        p = self.proc
        if not p or not p.stdout:
            return
        try:
            while self.alive():
                raw = p.stdout.readline(max(1, self.max_line_bytes + 1))
                if not raw:
                    break
                size = len(raw.encode("utf-8", "replace"))
                self._stdout_bytes += size
                if (self.max_line_bytes and size > self.max_line_bytes) or (
                        self.max_line_bytes and not raw.endswith("\n")
                        and size >= self.max_line_bytes):
                    self._limit_triggered(
                        "MCP stdout 单行超过 %d 字节，已终止" % self.max_line_bytes)
                    return
                if self.max_total_bytes and self._stdout_bytes > self.max_total_bytes:
                    self._limit_triggered(
                        "MCP stdout 总量超过 %d 字节，已终止" % self.max_total_bytes)
                    return
                raw = (raw or "").strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    self._stderr_tail.append("[stdout] " + raw[:160])
                    continue
                if not isinstance(msg, dict):
                    continue
                rid = msg.get("id")
                if rid is None:
                    continue
                with self._lock:
                    slot = self._pending.pop(rid, None)
                if not slot:
                    continue
                if "error" in msg:
                    slot["error"] = msg["error"]
                else:
                    slot["result"] = msg.get("result")
                slot["event"].set()
        except Exception as e:
            self._stderr_tail.append("[reader] %s" % str(e)[:120])
        finally:
            self._alive = False
            with self._lock:
                slots = list(self._pending.values())
                self._pending.clear()
            for s in slots:
                s["error"] = {"message": "子进程已退出"}
                s["event"].set()

    def _drain_stderr(self):
        """Drain stderr and enforce a byte budget so a child cannot flood us."""
        p = self.proc
        if not p or not p.stderr:
            return
        try:
            while self.alive():
                raw = p.stderr.readline(64 * 1024)
                if not raw:
                    break
                size = len(raw.encode("utf-8", "replace"))
                self._stderr_bytes += size
                if self.max_stderr_bytes and self._stderr_bytes > self.max_stderr_bytes:
                    self._limit_triggered(
                        "MCP stderr 总量超过 %d 字节，已终止" % self.max_stderr_bytes)
                    return
                raw = (raw or "").strip()
                if raw:
                    self._stderr_tail.append(raw[:160])
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def diagnostics(self):
        """给界面看的诊断信息（握手失败时最有用）"""
        parts = []
        if self.last_error:
            parts.append(self.last_error)
        if self.proc is not None and not self.alive():
            parts.append("退出码: %s" % (self.proc.poll(),))
        if self._stderr_tail:
            parts.append("最近输出: " + " | ".join(list(self._stderr_tail)[-4:]))
        return " ；".join(parts) or "无"

    # ------------------------------------------------------------ MCP 方法

    def list_tools(self):
        """拉取工具列表；失败返回 None 并把原因写进 last_error"""
        try:
            r = self._request("tools/list", {})
        except Exception as e:
            self.last_error = str(e)[:120]
            return None
        tools = []
        if isinstance(r, dict):
            for t in (r.get("tools") or []):
                if not isinstance(t, dict):
                    continue
                tools.append({
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema") or {},
                    "_server": self.name,
                    "_transport": "stdio",
                })
        self.tools = tools
        return tools

    def call_tool(self, tool_name, args=None, timeout=90):
        """调用工具，返回 {ok, 结果/错误, ...}"""
        try:
            r = self._request("tools/call",
                              {"name": tool_name, "arguments": args or {}},
                              timeout=timeout)
        except Exception as e:
            return {"ok": False, "错误": str(e)[:160]}
        return {"ok": not (isinstance(r, dict) and r.get("isError")),
                "结果": _flatten_content(r),
                "原始": r}

    def ping(self):
        r = self.list_tools()
        return {"ok": r is not None, "工具数": len(r or []),
                "诊断": self.diagnostics()}


def _flatten_content(result):
    """把 tools/call 的 content 数组压成可读文本"""
    if not isinstance(result, dict):
        return str(result)[:500]
    parts = []
    for c in (result.get("content") or []):
        if not isinstance(c, dict):
            parts.append(str(c))
            continue
        if c.get("type") == "text":
            parts.append(str(c.get("text", "")))
        else:
            parts.append("[%s]" % c.get("type", "?"))
    return "\n".join(parts)[:2000] if parts else str(result)[:500]
