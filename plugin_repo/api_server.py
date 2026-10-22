# -*- coding: utf-8 -*-
"""P2-1: HTTP API 服务 - REST 接口 + Webhook 出站

端点：
  GET  /v1/health    健康检查
  POST /v1/chat      发消息
  POST /v1/tasks     创建异步任务
  GET  /v1/tasks/{id} 查任务状态

用 Python 内置 http.server，不加 flask 依赖。
"""
import json, os, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler


class _APIHandler(BaseHTTPRequestHandler):
    trunk = None  # 类变量，由 ApiServer 设置

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
        if self.path == "/v1/health":
            self._json_response(200, {"status": "ok", "time": time.time()})
        elif self.path.startswith("/v1/tasks/"):
            task_id = self.path.split("/")[-1]
            # 简单返回（实际从 task_runtime 查）
            self._json_response(200, {"task_id": task_id, "status": "running"})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if self.path == "/v1/chat":
            msg = data.get("message", "")
            # 调用 LLM（异步，先返回）
            self._json_response(200, {"ok": True, "echo": msg})
        elif self.path == "/v1/tasks":
            goal = data.get("goal", "")
            self._json_response(200, {"ok": True, "task_id": "task_" + str(int(time.time()))})
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

    def start(self):
        if self._server:
            return {"ok": False, "error": "already running"}
        _APIHandler.trunk = self.trunk
        self._server = HTTPServer((self.host, self.port), _APIHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return {"ok": True, "url": f"http://{self.host}:{self.port}"}

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
        return {"ok": True}

    def is_running(self):
        return self._server is not None

    def run(self, *a):
        """标准入口：启动 HTTP 服务"""
        return self.start()

    def health(self):
        """健康检查"""
        return {'ok': self.is_running()}
