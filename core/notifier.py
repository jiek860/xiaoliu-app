# -*- coding: utf-8 -*-
"""统一通知出口：飞书 / 企业微信 / 钉钉 群机器人

为什么单独抽一层
----------------
feedback_dialog 原来直接 smtplib 发邮件，凭据是邮箱授权码 
那等于把邮箱控制权交出去（程序运行时必须把明文交给 smtplib.login()，
Nuitka / 加固壳都挡不住：断点、内存 dump 都能拿到）。
群机器人 webhook 不一样：它只是一个"公开地址"，泄露了最坏是被往群里
发消息，删掉机器人重建即可。所以反馈通道应该走这里。

三个平台协议略有差异（飞书/钉钉支持加签），统一成：
    ok, err = Notifier(config).send("文本")
用 config 里的 notify_channel 切换，调用方不用改代码。

注意：加签只能挡"随手复制 URL 乱发"的人  secret 同样在客户端里，
真能逆向的人还是抠得出来。要防刷只能靠服务端限流。
"""
from core.safe_http import open_url as safe_open_url
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

CHANNELS = ("feishu", "wecom", "dingtalk")


def _post_json(url, payload, timeout=8, trunk=None):
    # 只允许 http/https，并统一经过出站网络策略。
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("不安全的URL: %s" % url[:30])
    try:
        from core.net_guard import get_net_guard
        d = get_net_guard(trunk).check(
            url, module="notifier", purpose="notify", method="POST")
        if not d.get("allow"):
            raise ValueError("网络策略拒绝: " + str(d.get("reason")))
    except ValueError:
        raise
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with safe_open_url(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


class Notifier:
    """从 config 读通道配置，发一条文本到群机器人"""

    def __init__(self, config=None, trunk=None):
        self.cfg = config or {}
        self.trunk = trunk

    def channel(self):
        """返回实际要用的通道名；没配置返回空串"""
        c = str(self.cfg.get("notify_channel", "") or "").strip().lower()
        if c in CHANNELS:
            return c
        # 没显式选就按"谁有地址用谁"兜底，省得用户填了地址却忘了选通道
        for k, name in (("feishu_webhook", "feishu"),
                        ("wecom_webhook", "wecom"),
                        ("dingtalk_webhook", "dingtalk")):
            if self.cfg.get(k):
                return name
        return ""

    def send(self, text, timeout=8):
        """返回 (成功?, 失败原因)。不抛异常。"""
        ch = self.channel()
        if not ch:
            return False, "没有配置通知通道"
        try:
            if ch == "feishu":
                return self._feishu(text, timeout)
            if ch == "wecom":
                return self._wecom(text, timeout)
            return self._dingtalk(text, timeout)
        except Exception as e:
            return False, "%s: %s" % (type(e).__name__, str(e)[:100])

    # ---------------- 飞书 ----------------
    @staticmethod
    def _feishu_sign(secret, timestamp):
        """飞书官方算法：key = 'timestamp\nsecret'，消息体为空，HMAC-SHA256 后 base64"""
        s = "%s\n%s" % (timestamp, secret)
        return base64.b64encode(
            hmac.new(s.encode("utf-8"), b"", hashlib.sha256).digest()
        ).decode("utf-8")

    def _feishu(self, text, timeout=8):
        url = self.cfg.get("feishu_webhook", "")
        if not url:
            return False, "没有配置 feishu_webhook"
        payload = {"msg_type": "text", "content": {"text": text}}
        secret = self.cfg.get("feishu_secret", "")
        if secret:
            ts = str(int(time.time()))
            payload["timestamp"] = ts
            payload["sign"] = self._feishu_sign(secret, ts)
        body = (_post_json(url, payload, timeout, self.trunk)
                if self.trunk is not None else _post_json(url, payload, timeout))
        flat = body.replace(" ", "")
        ok = ('"code":0' in flat) or ('"StatusCode":0' in flat)
        return (True, "") if ok else (False, body[:150])

    # ---------------- 企业微信 ----------------
    def _wecom(self, text, timeout=8):
        url = self.cfg.get("wecom_webhook", "")
        if not url:
            return False, "没有配置 wecom_webhook"
        body = (_post_json(url, {"msgtype": "text", "text": {"content": text}}, timeout, self.trunk)
                if self.trunk is not None else _post_json(url, {"msgtype": "text", "text": {"content": text}}, timeout))
        ok = '"errcode":0' in body.replace(" ", "")
        return (True, "") if ok else (False, body[:150])

    # ---------------- 钉钉（支持加签） ----------------
    @staticmethod
    def _dingtalk_sign(secret, timestamp):
        s = "%s\n%s" % (timestamp, secret)
        h = hmac.new(secret.encode("utf-8"), s.encode("utf-8"),
                     digestmod=hashlib.sha256).digest()
        return urllib.parse.quote_plus(base64.b64encode(h))

    def _dingtalk(self, text, timeout=8):
        url = self.cfg.get("dingtalk_webhook", "")
        if not url:
            return False, "没有配置 dingtalk_webhook"
        secret = self.cfg.get("dingtalk_secret", "")
        if secret:
            ts = str(round(time.time() * 1000))
            url = "%s&timestamp=%s&sign=%s" % (
                url, ts, self._dingtalk_sign(secret, ts))
        body = (_post_json(url, {"msgtype": "text", "text": {"content": text}}, timeout, self.trunk)
                if self.trunk is not None else _post_json(url, {"msgtype": "text", "text": {"content": text}}, timeout))
        ok = '"errcode":0' in body.replace(" ", "")
        return (True, "") if ok else (False, body[:150])
