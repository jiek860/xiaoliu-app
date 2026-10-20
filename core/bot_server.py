# -*- coding: utf-8 -*-
"""机器人服务 v2.0 - 企业微信 + 钉钉，收到消息AI处理后回复

发送统一走 core/notifier（那边有说明：群机器人 webhook 是"公开地址"，
比邮箱授权码安全得多）。这里只负责两件事：
    1. 起一个本地 HTTP 回调，接收企业微信/钉钉的消息
    2. 把消息交给 trunk.reply()，再原路发回去

历史：原来 send_wecom / send_dingtalk 各写了一份 urllib 拼接，
和 core/notifier.py 重复。2026-10 收敛到 Notifier，公开 API 不变
（gui/bot_dialog.py 的 set_wecom_webhook / send_wecom 照常可用）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import hmac
import json
import secrets
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from core.notifier import Notifier


class BotServer:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.server = None
        self.thread = None
        self.running = False
        self.wecom_webhook = ""
        self.dingtalk_webhook = ""
        self.dingtalk_secret = ""
        self.port = 9000
        self.token = secrets.token_urlsafe(24)
        self.max_body = 64 * 1024

    def set_wecom_webhook(self, url):
        self.wecom_webhook = url

    def set_dingtalk_webhook(self, url, secret=""):
        self.dingtalk_webhook = url
        if secret:
            self.dingtalk_secret = secret

    def _notifier(self, channel, url):
        """拼一个只启用单个通道的 Notifier（配置是"公开地址"，不是密钥）"""
        return Notifier({
            "notify_channel": channel,
            "wecom_webhook": url if channel == "wecom" else "",
            "dingtalk_webhook": url if channel == "dingtalk" else "",
            "dingtalk_secret": self.dingtalk_secret,
        })

    def send_wecom(self, text):
        """发消息到企业微信群（实现在 core/notifier）"""
        if not self.wecom_webhook:
            return False
        ok, err = self._notifier("wecom", self.wecom_webhook).send(text)
        if not ok:
            print("企业微信发送失败: %s" % err)
        return ok

    def send_dingtalk(self, text):
        """发消息到钉钉群（实现在 core/notifier）"""
        if not self.dingtalk_webhook:
            return False
        ok, err = self._notifier("dingtalk", self.dingtalk_webhook).send(text)
        if not ok:
            print("钉钉发送失败: %s" % err)
        return ok

    def handle_message(self, text):
        """收到消息后调用 trunk.reply()；外部机器人默认禁用工具。"""
        if not self.trunk:
            return "（程序未加载）"
        try:
            self.trunk._remote_tool_locked = True
            try:
                self.trunk._remote_tools_allowed = bool(
                    (getattr(self.trunk, "config", {}) or {}).get("bot_allow_tools", False))
            except Exception:
                self.trunk._remote_tools_allowed = False
            return self.trunk.reply(text)
        except Exception as e:
            return f"处理出错: {str(e)[:80]}"
        finally:
            for _attr in ("_remote_tool_locked", "_remote_tools_allowed"):
                try:
                    delattr(self.trunk, _attr)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

    def start(self, port=9000):
        """启动HTTP服务器"""
        self.port = port
        bot = self

        class Handler(BaseHTTPRequestHandler):
            def _host_ok(self):
                raw = (self.headers.get("Host") or "").strip().lower()
                host = raw.rsplit(":", 1)[0] if ":" in raw and not raw.startswith("[") else raw
                return host in ("127.0.0.1", "localhost", "::1", "[::1]")

            def _origin_ok(self):
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                try:
                    p = urllib.parse.urlparse(origin)
                    return (p.hostname or "").lower() in ("127.0.0.1", "localhost", "::1")
                except Exception:
                    return False

            def _auth_ok(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                given = (q.get("token", [""])[0]
                         or self.headers.get("X-X6-Token") or "")
                return bool(given) and hmac.compare_digest(str(given), bot.token)

            def _deny(self, code):
                # 把已发送的请求体读干净，避免服务端先 close 时客户端
                # 还在写 body，Windows 上表现为 ConnectionAbortedError。
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    if 0 < n <= bot.max_body:
                        self.rfile.read(n)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
                body = b'{"ok":false}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

            def do_POST(self):
                if not self._host_ok() or not self._origin_ok():
                    self._deny(403); return
                if not self._auth_ok():
                    self._deny(401); return
                try:
                    content_length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    content_length = -1
                if content_length < 0 or content_length > bot.max_body:
                    self._deny(413); return
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    self._deny(415); return
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
            return {"成功": True, "端口": port, "token": self.token,
                    "回调地址": "http://127.0.0.1:%d/{wecom|dingtalk}?token=%s"
                                % (port, self.token)}
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
            "钉钉": "已配置" if self.dingtalk_webhook else "未配置",
            "token": self.token,
        }
