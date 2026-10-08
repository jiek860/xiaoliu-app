# -*- coding: utf-8 -*-
"""移动端网页 v6.1 - 手机浏览器访问电脑上的小6

在原 手机远程.py（v6.0）基础上加固：
  1. 继承 BaseModule，符合模块协议（__init__(trunk=None) / run()）
  2. 访问令牌：启动时生成一次性令牌，手机地址必须带 ?k=令牌，
     否则 /chat 一律 403 —— 避免局域网内任何人遥控本机
  3. 监听地址可配（data/config.json 的 mobile_bind），默认 0.0.0.0 供手机访问，
     只在本机用可改 127.0.0.1
  4. 端口可配（mobile_port，默认 8765）
"""
import json
import os
import secrets
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from modules.base import BaseModule

HTML = '''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>小6</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}
.header{background:#1e293b;padding:12px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #334155}
.dot{width:10px;height:10px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e}
.title{font-size:16px;font-weight:600}
.chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:85%;padding:10px 14px;border-radius:16px;line-height:1.5;font-size:15px;word-break:break-word}
.user{align-self:flex-end;background:#3b82f6;color:#fff;border-bottom-right-radius:4px}
.bot{align-self:flex-start;background:#1e293b;border-bottom-left-radius:4px}
.input{background:#1e293b;padding:10px;display:flex;gap:8px;border-top:1px solid #334155}
.input input{flex:1;padding:10px 14px;border:none;border-radius:20px;background:#0f172a;color:#fff;font-size:15px;outline:none}
.input button{padding:10px 18px;border:none;border-radius:20px;background:#3b82f6;color:#fff;font-size:15px;font-weight:600}
.typing{font-size:12px;color:#64748b;padding:4px 16px}
</style></head>
<body>
<div class="header"><div class="dot"></div><div class="title">小6</div></div>
<div class="chat" id="chat"></div>
<div class="typing" id="typing"></div>
<div class="input">
<input id="q" placeholder="说点什么..." autofocus>
<button onclick="send()">发送</button>
</div>
<script>
const TOKEN = "__TOKEN__";
const chat=document.getElementById('chat');
const typing=document.getElementById('typing');
function add(cls,text){const d=document.createElement('div');d.className='msg '+cls;d.innerText=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight}
async function send(){
const q=document.getElementById('q').value.trim();if(!q)return;
add('user',q);document.getElementById('q').value='';
typing.innerText='思考中...';
try{
const r=await fetch('/chat?k='+encodeURIComponent(TOKEN)+'&q='+encodeURIComponent(q));
const d=await r.json();
add('bot',d.回答||JSON.stringify(d));
}catch(e){add('bot','连接失败:'+e)}
typing.innerText='';
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')send()});
add('bot','你好！我在手机上了。');
</script></body></html>'''


class MobileRemote(BaseModule):
    NAME = "mobile_remote"
    VERSION = "6.1"

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.port = int(os.environ.get("MOBILE_REMOTE_PORT", 8765))
        self.bind = "0.0.0.0"
        if trunk is not None:
            try:
                self.port = int(trunk.config.get("mobile_port", self.port))
                self.bind = str(trunk.config.get("mobile_bind", self.bind))
            except Exception:
                pass
        self.token = ""
        self.server = None

    def _ensure_token(self):
        if not self.token:
            self.token = secrets.token_urlsafe(9)
        return self.token

    def _lan_ip(self):
        """猜一个局域网 IP，方便直接把网址念给用户"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def start(self):
        if self.server:
            return "移动端已在运行"
        token = self._ensure_token()
        trunk = self.trunk
        html = HTML.replace("__TOKEN__", token).encode("utf-8")

        class H(BaseHTTPRequestHandler):
            def _json(self, obj, code=200):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                try:
                    u = urllib.parse.urlparse(self.path)
                    qs = urllib.parse.parse_qs(u.query)
                    if u.path == "/chat":
                        # 令牌校验：不通过一律拒绝，避免局域网被随意遥控
                        if qs.get("k", [""])[0] != token:
                            self._json({"error": "令牌无效"}, 403)
                            return
                        q = (qs.get("q", [""])[0] or "").strip()
                        if not q:
                            self._json({"error": "缺少参数 q"}, 400)
                            return
                        try:
                            r = trunk.reply(q) if trunk else "未连接躯干"
                        except Exception as e:
                            r = "出错: " + str(e)[:80]
                        self._json({"回答": r})
                        return
                    # 首页
                    if u.path not in ("/", "/index.html"):
                        self._json({"error": "未知路径"}, 404)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                except Exception:
                    pass

            def log_message(self, *a):
                pass

        try:
            self.server = HTTPServer((self.bind, self.port), H)
        except OSError as e:
            return "移动端启动失败(端口 %d 可能被占用): %s" % (self.port, str(e)[:60])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        ip = self._lan_ip() if self.bind == "0.0.0.0" else self.bind
        return ("移动端已启动: http://%s:%d/?k=%s  （手机与本机需在同一局域网；"
                "令牌是访问凭证，别外传）" % (ip, self.port, token))

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            return "移动端已停止"
        return "移动端未运行"

    def run(self, *a):
        if a and a[0] == "stop":
            return self.stop()
        if a and a[0] == "start":
            return self.start()
        return {"端口": self.port, "监听": self.bind,
                "状态": "运行中" if self.server else "未启动",
                "网页": "http://%s:%d/" % (self.bind, self.port),
                "令牌": self.token or "(启动后生成)"}
