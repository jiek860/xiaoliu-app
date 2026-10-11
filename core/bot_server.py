# -*- coding: utf-8 -*-
"""机器人服务 v2.0 - 企业微信 + 钉钉，收到消息AI处理后回复"""
import json, threading, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler


class BotServer:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.server = None
        self.thread = None
        self.running = False
        self.wecom_webhook = ""
        self.dingtalk_webhook = ""
        self.port = 9000
        self.token = ""  # BUG-09: 访问token校验

    def set_wecom_webhook(self, url):
        self.wecom_webhook = url

    def set_dingtalk_webhook(self, url):
        self.dingtalk_webhook = url

    def _safe_url(self, url):
        """安全检查：只允许http/https"""
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("不安全的URL: " + url[:30])
        return url

    def send_wecom(self, text):
        """发消息到企业微信群"""
        if not self.wecom_webhook:
            return False
        try:
            self._safe_url(self.wecom_webhook)
            data = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
            req = urllib.request.Request(self.wecom_webhook, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception as e:
            print(f"企业微信发送失败: {e}")
            return False

    def send_dingtalk(self, text):
        """发消息到钉钉群"""
        if not self.dingtalk_webhook:
            return False
        try:
            self._safe_url(self.dingtalk_webhook)
            data = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
            req = urllib.request.Request(self.dingtalk_webhook, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception as e:
            print(f"钉钉发送失败: {e}")
            return False

    def handle_message(self, text):
        """BUG-08: 收到消息后，调用trunk.reply()，带人格/记忆/闭环"""
        if not self.trunk:
            return "（程序未加载）"
        try:
            return self.trunk.reply(text)
        except Exception as e:
            return f"处理出错: {str(e)[:80]}"

    def start(self, port=9000):
        """启动HTTP服务器"""
        self.port = port
        bot = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")

                # 企业微信回调
                if "/wecom" in self.path:
                    try:
                        data = json.loads(body)
                        text = data.get("text", {}).get("content", "")
                        if text:
                            reply = bot.handle_message(text)
                            bot.send_wecom(reply)
                    except Exception as e:
                        print(f"企业微信处理失败: {e}")

                # 钉钉回调
                elif "/dingtalk" in self.path:
                    try:
                        data = json.loads(body)
                        text = data.get("text", {}).get("content", "")
                        if text:
                            reply = bot.handle_message(text)
                            bot.send_dingtalk(reply)
                    except Exception as e:
                        print(f"钉钉处理失败: {e}")

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, format, *args):
                pass  # 静默日志

        try:
            self.server = HTTPServer(("127.0.0.1", port), Handler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.running = True
            return {"成功": True, "端口": port}
        except Exception as e:
            return {"成功": False, "错误": str(e)[:80]}

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.running = False
            return {"成功": True}
        return {"成功": False}

    def status(self):
        return {
            "运行中": self.running,
            "端口": self.port,
            "企业微信": "已配置" if self.wecom_webhook else "未配置",
            "钉钉": "已配置" if self.dingtalk_webhook else "未配置"
        }

