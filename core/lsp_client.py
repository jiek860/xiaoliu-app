# -*- coding: utf-8 -*-
"""语言服务（LSP）客户端：跳定义 / 引用 / 重命名 / 诊断 / 补全 / hover / 格式化。

要解决什么
----------
工作台原来只有 jedi 补全：跨文件跳定义、查找引用、重命名符号一个都没有，
差距不在"补全词多不多"，而在**没有语义层**。主流 IDE 靠的是 LSP：
一个子进程 + stdin/stdout 上的 JSON-RPC。本模块是那套协议的实现：

  ① 路由     按扩展名挑服务（pylsp / pyright / typescript-language-server / clangd）
  ② 增量同步 didChange 只发改动那一段，不全量替换（深度②）
  ③ 能力     initialize/capabilities、诊断、补全、hover、code action、format range

帧编解码 / 位置换算 / 结果归一 / 重命名落盘在 `core/lsp_protocol.py`（纯函数）。

没装语言服务时**全部安静地不可用**：`client_for()` 返回 None，上层拿到
None 就退回原来的 jedi / ruff 路径，不报错、不弹窗（验收要求之一）。
⚠️ 本模块只依赖标准库，不 import Qt。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading

from core.lsp_protocol import (  # noqa: F401 - 对外转发，GUI 只 import 本模块
    apply_text_edits, apply_workspace_edit, completion_items, decode_message,
    encode_message, hover_text, incremental_change, locations_of,
    offset_to_position, path_for_uri, position_to_offset, uri_for_path,
    workspace_edit_changes)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

# (扩展名, languageId, 候选命令数组, 显示名)；装了哪个用哪个（深度③）
SERVER_ROUTES = (
    ((".py", ".pyw", ".pyi"), "python",
     (("pylsp",), ("pyright-langserver", "--stdio"),
      ("jedi-language-server",)), "Python 语言服务"),
    ((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue"), "typescript",
     (("typescript-language-server", "--stdio"),), "TypeScript 语言服务"),
    ((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hxx"), "cpp",
     (("clangd",),), "C/C++ 语言服务"),
    ((".rs",), "rust", (("rust-analyzer",),), "Rust 语言服务"),
    ((".go",), "go", (("gopls",),), "Go 语言服务"),
)

_LANGUAGES = tuple(row[1] for row in SERVER_ROUTES)
_HINT = {
    "typescript": "npm i -g typescript typescript-language-server",
    "cpp": "安装 LLVM 后把 clangd 加进 PATH",
    "rust": "rustup component add rust-analyzer",
    "go": "go install golang.org/x/tools/gopls@latest",
}
# Python 的装法不写死在这里：统一走 core.error_text.install_cmd（带国内源），
# 免得又多一处"给了 pip install 却没带源"的漏网之鱼。


def _python_hint():
    try:
        from core.error_text import install_cmd
        return install_cmd("python-lsp-server")
    # 静默是故意的：拼提示失败不该让"查可用性"挂掉
    except Exception as e:
        _x6_swallowed(__name__, e, "python lsp install hint")
        return ""


def _which(name):
    try:
        return shutil.which(str(name)) or ""
    except (OSError, TypeError):
        return ""


def server_for(path):
    """按扩展名挑服务：返回 {language, name, argv, available}；未知类型 None。"""
    ext = os.path.splitext(str(path or "").lower())[1]
    for exts, language, cands, label in SERVER_ROUTES:
        if ext not in exts:
            continue
        for argv in cands:
            exe = _which(argv[0])
            if exe:
                return {"language": language, "name": label,
                        "argv": [exe] + list(argv[1:]), "available": True}
        return {"language": language, "name": label,
                "argv": list(cands[0]), "available": False}
    return None


def detect():
    """每种语言当前有没有可用服务（自检/设置页展示用）。"""
    out = {}
    for _exts, language, cands, label in SERVER_ROUTES:
        picked = ""
        for argv in cands:
            if _which(argv[0]):
                picked = " ".join(argv)
                break
        out[language] = {"名称": label, "可用": bool(picked),
                         "命令": picked or " ".join(cands[0]),
                         "装法": install_hint(language)}
    return out


def available_for(path):
    s = server_for(path)
    return bool(s and s.get("available"))


def install_hint(path_or_language=""):
    """缺服务时给用户的安装提示（路径 / 语言名都能传）。"""
    raw = str(path_or_language or "")
    language = raw if raw in _LANGUAGES else ""
    if not language:
        server = server_for(raw)
        language = (server or {}).get("language", "")
    if language == "python":
        return _python_hint()
    return _HINT.get(language, "")


class LspClient:
    """一个工作区一条语言服务连接。

    线程模型：一个 daemon 读线程 + 调用方线程。request() 用 Event 等回包，
    超时返回 {"ok": False}，**绝不抛异常**（界面不能因为服务挂了而崩）。
    """

    def __init__(self, root, path, server=None, timeout=2.0):
        self.root = os.path.abspath(str(root or os.getcwd()))
        self.path = os.path.abspath(str(path or ""))
        self.server = server or server_for(self.path)
        self.timeout = float(timeout)
        self.diagnostics = {}
        self.capabilities = {}
        self.sent = []           # 未启动时的"外发记录"（测试可读）
        self._proc = None
        self._alive = False
        self._id = 0
        self._version = 0
        self._text = ""
        self._buf = b""
        self._lock = threading.Lock()
        self._pending = {}

    # ---- 生命周期 ----
    def start(self):
        """拉起服务并握手；装不上/起不来都返回 False，不抛异常。"""
        if self._proc is not None:
            return self._alive
        if not (self.server or {}).get("available"):
            return False
        try:
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            self._proc = subprocess.Popen(
                list(self.server["argv"]), cwd=self.root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0, creationflags=flags)
        except (OSError, ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "spawn language server")
            self._proc = None
            return False
        self._alive = True
        threading.Thread(target=self._read_loop, args=(self._proc,),
                         daemon=True).start()
        init = self.request("initialize", self._init_params(), timeout=8.0)
        if not init.get("ok"):
            self.stop()
            return False
        self.capabilities = (init.get("result") or {}).get("capabilities") or {}
        self.notify("initialized", {})
        return True

    def stop(self):
        """先优雅 shutdown/exit，再 kill，最后清状态。"""
        proc, self._proc = self._proc, None
        self._alive = False
        self._fail_pending("语言服务已停止")
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(encode_message(
                    {"jsonrpc": "2.0", "id": self._next_id(),
                     "method": "shutdown", "params": {}}))
                proc.stdin.write(encode_message(
                    {"jsonrpc": "2.0", "method": "exit", "params": {}}))
                proc.stdin.flush()
        except Exception as e:  # 静默是故意的 - 服务已退出时写不进去
            _x6_swallowed(__name__, e, "lsp shutdown")
        try:
            proc.wait(timeout=1.5)
        except Exception as e:  # 静默是故意的 - 超时就强杀，不留孤儿进程
            _x6_swallowed(__name__, e, "lsp wait")
            try:
                proc.kill()
            except Exception as e2:  # 静默是故意的
                _x6_swallowed(__name__, e2, "lsp kill")

    def _init_params(self):
        return {
            "processId": os.getpid(),
            "clientInfo": {"name": "小6工作台", "version": "25.5"},
            "rootUri": uri_for_path(self.root),
            "workspaceFolders": [{
                "uri": uri_for_path(self.root),
                "name": os.path.basename(self.root) or "workspace"}],
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True,
                                        "dynamicRegistration": False},
                    "completion": {"completionItem": {
                        "snippetSupport": False}},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "definition": {"linkSupport": True},
                    "references": {},
                    "rename": {},
                    "codeAction": {},
                    "formatting": {},
                    "rangeFormatting": {},
                    "publishDiagnostics": {"relatedInformation": False},
                },
                "workspace": {
                    "workspaceEdit": {"documentChanges": False},
                    "applyEdit": False,
                    "executeCommand": {},
                },
            },
        }

    # ---- 收发 ----
    def _next_id(self):
        with self._lock:
            self._id += 1
            return self._id

    def _write(self, obj):
        data = encode_message(obj)
        proc = self._proc
        if proc is None or not proc.stdin:
            self.sent.append(obj)
            return False
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except Exception as e:  # 静默是故意的 - 服务退出后写入失败按可用性处理
            _x6_swallowed(__name__, e, "lsp write")
            self._alive = False
            return False

    def notify(self, method, params=None):
        return self._write({"jsonrpc": "2.0", "method": method,
                            "params": params or {}})

    def request(self, method, params=None, timeout=None):
        """同步请求：返回 {"ok", "result"} / {"ok": False, "reason"}。"""
        if not self._alive and self._proc is None:
            return {"ok": False, "reason": "语言服务未启动"}
        mid = self._next_id()
        event = threading.Event()
        with self._lock:
            self._pending[mid] = {"event": event, "result": None,
                                  "error": None}
        if not self._write({"jsonrpc": "2.0", "id": mid, "method": method,
                            "params": params or {}}):
            with self._lock:
                self._pending.pop(mid, None)
            return {"ok": False, "reason": "语言服务已断开"}
        if not event.wait(timeout if timeout is not None else self.timeout):
            with self._lock:
                self._pending.pop(mid, None)
            return {"ok": False, "reason": "语言服务超时：%s" % method}
        with self._lock:
            slot = self._pending.pop(mid, None) or {}
        if slot.get("error"):
            return {"ok": False, "reason": str(slot["error"])[:300]}
        return {"ok": True, "result": slot.get("result")}

    def _fail_pending(self, reason):
        with self._lock:
            slots = list(self._pending.values())
            self._pending.clear()
        for slot in slots:
            slot["error"] = reason
            slot["event"].set()

    def _read_loop(self, proc):
        stdout = proc.stdout
        while True:
            try:
                chunk = stdout.read(4096)
            except Exception as e:  # 静默是故意的 - 进程被杀时读线程自然结束
                _x6_swallowed(__name__, e, "lsp read")
                break
            if not chunk:
                break
            self._buf += chunk
            while True:
                msg, rest = decode_message(self._buf)
                if msg is None and rest == self._buf:
                    break
                self._buf = rest
                if msg is None:
                    continue
                self._dispatch(msg)
        self._alive = False
        self._fail_pending("语言服务已退出")

    def feed(self, data):
        """把一段服务端字节喂进来（测试用，与读线程同一套解析路径）。"""
        self._buf += data
        while True:
            msg, rest = decode_message(self._buf)
            if msg is None and rest == self._buf:
                return
            self._buf = rest
            if msg is not None:
                self._dispatch(msg)

    def _dispatch(self, msg):
        """处理一条服务端消息（测试可直接喂 dict）。"""
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        if method == "textDocument/publishDiagnostics":
            params = msg.get("params") or {}
            path = path_for_uri(params.get("uri"))
            if path:
                self.diagnostics[path] = list(params.get("diagnostics") or [])
            return
        if method and "id" in msg:
            # 服务端反向请求（配置/注册能力）：一律回"不支持"，不阻塞
            self._write({"jsonrpc": "2.0", "id": msg.get("id"),
                         "error": {"code": -32601, "message": "unsupported"}})
            return
        mid = msg.get("id")
        if mid is None:
            return
        with self._lock:
            slot = self._pending.get(mid)
        if slot is None:
            return
        slot["result"] = msg.get("result")
        slot["error"] = msg.get("error")
        slot["event"].set()

    # ---- 文档同步 ----
    def _doc(self, path=None):
        return {"uri": uri_for_path(path or self.path)}

    def did_open(self, text="", path=None):
        self._text = text or ""
        self._version = 0
        return self.notify("textDocument/didOpen", {
            "textDocument": dict(self._doc(path),
                                 languageId=(self.server or {}).get(
                                     "language") or "plaintext",
                                 version=self._version, text=self._text)})

    def did_change(self, text, path=None):
        """增量同步：只发改动段（深度②）；没有改动就不发。"""
        change = incremental_change(self._text, text)
        self._text = text or ""
        if change is None:
            return None
        self._version += 1
        self.notify("textDocument/didChange", {
            "textDocument": dict(self._doc(path), version=self._version),
            "contentChanges": [change]})
        return change

    def did_save(self, path=None):
        return self.notify("textDocument/didSave", {
            "textDocument": self._doc(path)})

    def did_close(self, path=None):
        return self.notify("textDocument/didClose", {
            "textDocument": self._doc(path)})

    # ---- 能力（深度①） ----
    def _at(self, line, character):
        return {"textDocument": self._doc(),
                "position": {"line": max(0, int(line or 0)),
                             "character": max(0, int(character or 0))}}

    def definition(self, line, character):
        r = self.request("textDocument/definition", self._at(line, character))
        if not r.get("ok"):
            return {"ok": False, "locations": [],
                    "reason": r.get("reason", "")}
        return {"ok": True, "locations": locations_of(r.get("result"))}

    def references(self, line, character, include_declaration=True):
        params = self._at(line, character)
        params["context"] = {"includeDeclaration": bool(include_declaration)}
        r = self.request("textDocument/references", params)
        if not r.get("ok"):
            return {"ok": False, "locations": [],
                    "reason": r.get("reason", "")}
        return {"ok": True, "locations": locations_of(r.get("result"))}

    def rename(self, line, character, new_name):
        r = self.request("textDocument/rename", dict(
            self._at(line, character), newName=str(new_name or "")))
        if not r.get("ok"):
            return {"ok": False, "edit": {}, "reason": r.get("reason", "")}
        return {"ok": True, "edit": r.get("result") or {}}

    def hover(self, line, character):
        r = self.request("textDocument/hover", self._at(line, character))
        if not r.get("ok"):
            return {"ok": False, "text": "", "reason": r.get("reason", "")}
        return {"ok": True, "text": hover_text(r.get("result"))}

    def completion(self, line, character):
        r = self.request("textDocument/completion", self._at(line, character))
        if not r.get("ok"):
            return {"ok": False, "items": [], "reason": r.get("reason", "")}
        return {"ok": True, "items": completion_items(r.get("result"))}

    def format_range(self, start_line, end_line, tab_size=4):
        """只格式化某个行区间（1 基闭区间，深度⑥）。"""
        lo, hi = _span(start_line, end_line)
        return _edits_result(self.request("textDocument/rangeFormatting", {
            "textDocument": self._doc(),
            "range": {"start": {"line": lo - 1, "character": 0},
                      "end": {"line": hi, "character": 0}},
            "options": {"tabSize": tab_size, "insertSpaces": True},
        }))

    def format_document(self, tab_size=4):
        return _edits_result(self.request("textDocument/formatting", {
            "textDocument": self._doc(),
            "options": {"tabSize": tab_size, "insertSpaces": True},
        }))

    def code_action(self, start_line, end_line, diagnostics=None):
        lo, hi = _span(start_line, end_line)
        r = self.request("textDocument/codeAction", {
            "textDocument": self._doc(),
            "range": {"start": {"line": lo - 1, "character": 0},
                      "end": {"line": hi, "character": 0}},
            "context": {"diagnostics": list(diagnostics or [])},
        })
        if not r.get("ok"):
            return {"ok": False, "actions": [], "reason": r.get("reason", "")}
        actions = r.get("result") or []
        return {"ok": True, "actions": [a for a in actions
                                        if isinstance(a, dict)]}

    def diagnostics_for(self, path=None):
        key = os.path.normpath(os.path.abspath(str(path or self.path)))
        return list(self.diagnostics.get(key, []))


def _span(start_line, end_line):
    lo = max(1, int(start_line or 1))
    hi = max(lo, int(end_line or lo))
    return lo, hi


def _edits_result(r):
    if not r.get("ok"):
        return {"ok": False, "edits": [], "reason": r.get("reason", "")}
    return {"ok": True, "edits": [e for e in (r.get("result") or [])
                                  if isinstance(e, dict)]}


# ---------------------------------------------------------------- 客户端缓存
_CLIENTS = {}
_CACHE_LOCK = threading.Lock()


def client_for(root, path, autostart=True):
    """按根目录 + 语言拿一个已启动的客户端；没有可用服务返回 None。"""
    server = server_for(path)
    if not server or not server.get("available"):
        return None
    key = (os.path.abspath(str(root or os.getcwd())), server["language"])
    with _CACHE_LOCK:
        client = _CLIENTS.get(key)
        if client is not None and client._alive:
            return client
    client = LspClient(root, path, server)
    if autostart and not client.start():
        return None
    with _CACHE_LOCK:
        _CLIENTS[key] = client
    return client


def close_all():
    """退出时把起过的服务全关掉（不留孤儿进程）。"""
    with _CACHE_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        try:
            client.stop()
        # 静默是故意的：退出阶段的服务关闭失败不影响程序结束
        except Exception as e:
            _x6_swallowed(__name__, e, "lsp close_all")


def status():
    """自检入口：语言服务是否可用（不启动进程，只看命令在不在 PATH）。"""
    rows = detect()
    ok = [k for k, v in rows.items() if v["可用"]]
    missing = [v["名称"] for k, v in rows.items() if not v["可用"]]
    return {"可用": ok, "明细": rows,
            "摘要": ("%d/%d 种语言服务可用" % (len(ok), len(rows))
                     + ("；缺装：" + "、".join(missing) if missing else ""))}


try:
    import atexit as _atexit
    _atexit.register(close_all)
except Exception as e:  # 静默是故意的 - 注册失败不影响功能
    _x6_swallowed(__name__, e, "atexit lsp")
