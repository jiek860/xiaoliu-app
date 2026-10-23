# -*- coding: utf-8 -*-
"""P2-1: HTTP API 服务 - REST 接口 + Webhook 出站

端点：
  GET  /v1/health    健康检查
  POST /v1/chat      发消息
  POST /v1/tasks     创建异步任务
  GET  /v1/tasks/{id} 查任务状态

用 Python 内置 http.server，不加 flask 依赖。

不负责的事项：
  - 不做用户认证和鉴权（后续加）
  - 不做 Webhook 出站重试（后续加）
  - 不做请求限流（后续加）
"""
import json, os, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs



class _APIHandler(BaseHTTPRequestHandler):
    trunk = None  # 类变量，由 ApiServer 设置
    auth_token = None  # 访问令牌，由 ApiServer 设置

    def _check_auth(self):
        """检查 token 鉴权"""
        if not self.auth_token:
            return True  # 没设 token 就不鉴权
        # 从 URL 参数或 Header 拿 token
        token = None
        qs = parse_qs(urlparse(self.path).query)
        if qs.get("token"):
            token = qs["token"][0]
        else:
            token = self.headers.get("Authorization", "").replace("Bearer ", "")
        return token == self.auth_token

    def _json_response(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # 静默是故意的 - HTTP 访问日志不打到控制台

    def do_GET(self):
        path = urlparse(self.path).path
        # 健康检查不需要鉴权
        if path == "/v1/health":
            self._json_response(200, {"status": "ok", "time": time.time()})
            return

        # 其他端点都要鉴权
        if not self._check_auth():
            self._json_response(401, {"error": "unauthorized"})
            return

        if path == "/":
            # 返回简单的 HTML 聊天页面
            html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>小6 Web 控制台</title>
  <style>
    body { font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 0 20px; }
    #chat { border: 1px solid #ddd; height: 400px; overflow-y: auto; padding: 10px; margin-bottom: 10px; }
    .msg { margin: 8px 0; padding: 8px; border-radius: 8px; }
    .user { background: #e3f2fd; text-align: right; }
    .ai { background: #f5f5f5; }
    #input { width: 100%; padding: 10px; box-sizing: border-box; }
  </style>
</head>
<body>
  <h2>小6 Web 控制台</h2>
  <div id="chat"></div>
  <input id="input" placeholder="输入消息..." onkeydown="if(event.key==='Enter')send()">
  <script>
    const TOKEN = new URLSearchParams(location.search).get('token') || '';
    async function send() {
      const input = document.getElementById('input');
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';
      addMsg('user', msg);
      const r = await fetch('/v1/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN},
        body: JSON.stringify({message: msg})
      });
      const d = await r.json();
      addMsg('ai', d.reply || d.error || '...');
    }
    function addMsg(type, text) {
      const chat = document.getElementById('chat');
      const div = document.createElement('div');
      div.className = 'msg ' + type;
      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }
  </script>
</body>
</html>"""
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/v1/ws":
            # WebSocket 风格实时推送（简单版：长连接，推任务状态变化）
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                # 先推当前任务列表
                tasks = []
                if self.trunk:
                    tr = self.trunk.get_task_runtime()
                    if tr and hasattr(tr, "list_tasks"):
                        tasks = tr.list_tasks()
                msg = "EVENT: task_list %s\n" % json.dumps(tasks[:10], ensure_ascii=False)
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()

                # 每 2 秒推一次心跳
                for _i in range(15):
                    msg = "EVENT: heartbeat %d\n" % int(time.time())
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(2)
            except Exception:  # 静默是故意的：长连接断开自然结束
                pass
        elif path == "/tasks":
            # 任务管理页面（真的从 task_runtime 读）
            tasks = []
            try:
                if self.trunk:
                    tr = self.trunk.get_task_runtime()
                    if tr and hasattr(tr, "list_tasks"):
                        tasks = tr.list_tasks()
            except Exception:  # 静默是故意的：任务页读取失败显示空列表
                pass

            # 生成表格行
            rows = ""
            status_map = {
                "running": "⏳ 运行中", "completed": "✅ 完成",
                "failed": "❌ 失败", "pending": "⏸ 等待",
            }
            for t in tasks[:20]:
                status = status_map.get(t.get("status", ""), t.get("status", "?"))
                rows += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    t.get("task_id", "?"),
                    t.get("goal", "?")[:40],
                    status,
                    t.get("created_at", "?"),
                )

            html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>任务管理 - 小6 Web 控制台</title>
  <style>
    body { font-family: sans-serif; max-width: 1000px; margin: 20px auto; padding: 0 20px; }
    table { width: 100%%; border-collapse: collapse; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f5f5f5; }
    a { color: #4a9eff; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h2>任务管理（共 %d 个）</h2>
  <p><a href="/?token=%s">← 返回聊天</a></p>
  <table>
    <tr><th>任务ID</th><th>目标</th><th>状态</th><th>创建时间</th></tr>
    %s
  </table>
</body>
</html>""" % (len(tasks), self.auth_token or "", rows)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/v1/tasks/"):
            task_id = path.rstrip("/").split("/")[-1]
            try:
                tr = self.trunk.get_task_runtime() if self.trunk else None
                task = tr.get_task(task_id) if tr else None
                if not task:
                    self._json_response(404, {"ok": False, "error": "task not found"})
                else:
                    self._json_response(200, task)
            except Exception as e:
                self._json_response(500, {"ok": False, "error": str(e)[:200]})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        path = urlparse(self.path).path
        if path == "/v1/chat":
            msg = data.get("message", "")
            # 真的调用 trunk 的聊天接口
            if self.trunk and hasattr(self.trunk, "reply"):
                try:
                    reply = self.trunk.reply(msg)
                    self._json_response(200, {"ok": True, "reply": reply})
                except Exception as e:
                    self._json_response(500, {"ok": False, "error": str(e)[:200]})
            else:
                self._json_response(200, {"ok": True, "echo": msg, "note": "trunk 未加载，只 echo"})
        elif path == "/v1/tasks":
            goal = str(data.get("goal", "") or "").strip()
            if not goal:
                self._json_response(400, {"ok": False, "error": "goal is required"})
                return
            try:
                tr = self.trunk.get_task_runtime() if self.trunk else None
                if tr is None:
                    self._json_response(503, {"ok": False, "error": "task runtime unavailable"})
                    return
                task = tr.create(goal)
                tr.start(task["id"])
                self._json_response(200, {"ok": True, "task_id": task["id"],
                                          "status": task.get("status", "pending")})
            except Exception as e:
                self._json_response(500, {"ok": False, "error": str(e)[:200]})
        else:
            self._json_response(404, {"error": "not found"})


class ApiServer:
    """HTTP API 服务"""
    def __init__(self, trunk, host="127.0.0.1", port=8765):
        self.trunk = trunk
        self.host = host
        self.port = port
        self._server = None
        self._thread = None
        self._ws_loop = None
        self._ws_server = None
        self._ws_ready = False
        self._ws_error = ""

    def start(self):
        if self._server:
            return {"ok": False, "error": "already running"}
        _APIHandler.trunk = self.trunk
        # 生成随机 token
        import secrets
        self.auth_token = secrets.token_hex(16)
        _APIHandler.auth_token = self.auth_token
        self._server = HTTPServer((self.host, self.port), _APIHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        # 启动 WebSocket 服务器（另一个端口）
        self._ws_port = self.port + 1
        self._ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._ws_thread.start()

        # 给 WebSocket 线程一点时间；失败时如实返回错误，不假装可用
        for _ in range(10):
            if self._ws_ready or self._ws_error:
                break
            time.sleep(0.05)
        return {"ok": True,
                "url": f"http://{self.host}:{self.port}/?token={self.auth_token}",
                "ws_url": (f"ws://{self.host}:{self._ws_port}/?token={self.auth_token}"
                           if self._ws_ready else ""),
                "ws_ready": self._ws_ready,
                "ws_error": self._ws_error}

    def _run_websocket(self):
        """跑真 WebSocket 服务器"""
        import asyncio
        import websockets

        # 子线程里必须新建 event loop，不能用 get_event_loop()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def handler(websocket):
            # 校验 WebSocket 连接 token
            try:
                req = getattr(websocket, "request", None)
                req_path = getattr(req, "path", "") if req else ""
                ws_token = parse_qs(urlparse(req_path).query).get("token", [None])[0]
                if self.auth_token and ws_token != self.auth_token:
                    await websocket.close(code=1008)
                    return
            except Exception:  # 静默是故意的：handshake 属性不可读时按无 token 处理
                if self.auth_token:
                    await websocket.close(code=1008)
                    return
            # 推任务列表
            try:
                tasks = []
                if self.trunk:
                    tr = self.trunk.get_task_runtime()
                    if tr and hasattr(tr, "list_tasks"):
                        tasks = tr.list_tasks()
                await websocket.send(json.dumps({"type": "task_list", "data": tasks[:10]}, ensure_ascii=False))

                # 心跳
                while True:
                    await asyncio.sleep(2)
                    await websocket.send(json.dumps({"type": "heartbeat", "time": time.time()}))
            except Exception:  # 静默是故意的：连接断开即结束推送
                pass

        try:
            self._ws_loop = loop
            async def _serve():
                return await websockets.serve(handler, self.host, self._ws_port)
            self._ws_server = loop.run_until_complete(_serve())
            self._ws_ready = True
            loop.run_forever()
        except Exception as e:
            self._ws_ready = False
            self._ws_error = str(e)[:200]
        finally:
            try:
                loop.close()
            except Exception:  # 静默是故意的：loop 已关闭时忽略
                pass

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
        if self._ws_loop:
            try:
                import asyncio
                loop = self._ws_loop
                async def _shutdown():
                    try:
                        if self._ws_server is not None:
                            self._ws_server.close()
                            await self._ws_server.wait_closed()
                    finally:
                        loop.stop()
                loop.call_soon_threadsafe(lambda: asyncio.create_task(_shutdown()))
            except Exception:
                try:
                    self._ws_loop.stop()
                except Exception:  # 静默是故意的：stop 兜底不再抛
                    pass
            self._ws_loop = None
        self._ws_server = None
        self._ws_ready = False
        return {"ok": True}

    def is_running(self):
        return self._server is not None

    def run(self, *a):
        """标准入口：启动 HTTP 服务"""
        return self.start()

    def health(self):
        """健康检查"""
        return {'ok': self.is_running()}
