# -*- coding: utf-8 -*-
"""通知通道（飞书 / 企业微信 / 钉钉）单元测试

不联网：_post_json 被 monkeypatch 掉，只验"请求体形状"和"返回怎么判定"。
"""
import base64
import hashlib
import hmac
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import notifier as N  # noqa: E402


# ---------------------------------------------------------------- 通道选择

def test_channel_explicit():
    n = N.Notifier({"notify_channel": "feishu", "feishu_webhook": "x"})
    assert n.channel() == "feishu"


def test_channel_fallback_by_webhook():
    assert N.Notifier({"wecom_webhook": "x"}).channel() == "wecom"
    assert N.Notifier({"dingtalk_webhook": "x"}).channel() == "dingtalk"
    assert N.Notifier({"feishu_webhook": "x"}).channel() == "feishu"


def test_channel_empty():
    assert N.Notifier({}).channel() == ""
    assert N.Notifier(None).channel() == ""


def test_send_without_channel():
    ok, err = N.Notifier({}).send("hi")
    assert ok is False
    assert "没有配置" in err


# ---------------------------------------------------------------- 飞书

def test_feishu_plain(monkeypatch):
    seen = {}

    def fake(url, payload, timeout=8):
        seen["url"] = url
        seen["payload"] = payload
        return '{"code":0,"msg":"success"}'

    monkeypatch.setattr(N, "_post_json", fake)
    ok, err = N.Notifier({"feishu_webhook": "https://f/hook/x"}).send("你好")
    assert ok is True, err
    assert seen["payload"]["msg_type"] == "text"
    assert seen["payload"]["content"]["text"] == "你好"
    assert "timestamp" not in seen["payload"]
    assert "sign" not in seen["payload"]


def test_feishu_signed(monkeypatch):
    seen = {}

    def fake(url, payload, timeout=8):
        seen["payload"] = payload
        return '{"code":0}'

    monkeypatch.setattr(N, "_post_json", fake)
    n = N.Notifier({"feishu_webhook": "https://f/hook/x",
                    "feishu_secret": "sec"})
    assert n.send("hi")[0] is True
    p = seen["payload"]
    assert p["timestamp"] and p["sign"]
    want = base64.b64encode(hmac.new(
        ("%s\nsec" % p["timestamp"]).encode("utf-8"), b"",
        hashlib.sha256).digest()).decode("utf-8")
    assert p["sign"] == want


def test_feishu_error_body(monkeypatch):
    monkeypatch.setattr(N, "_post_json",
                        lambda *a, **k: '{"code":19001,"msg":"param error"}')
    ok, err = N.Notifier({"feishu_webhook": "https://f/hook/x"}).send("hi")
    assert ok is False
    assert "19001" in err


# ---------------------------------------------------------------- 企业微信

def test_wecom(monkeypatch):
    seen = {}

    def fake(url, payload, timeout=8):
        seen["payload"] = payload
        return '{"errcode":0,"errmsg":"ok"}'

    monkeypatch.setattr(N, "_post_json", fake)
    ok, err = N.Notifier({"wecom_webhook": "https://q/hook/x"}).send("hi")
    assert ok is True, err
    assert seen["payload"]["msgtype"] == "text"


# ---------------------------------------------------------------- 钉钉

def test_dingtalk_sign_appended(monkeypatch):
    seen = {}

    def fake(url, payload, timeout=8):
        seen["url"] = url
        return '{"errcode":0}'

    monkeypatch.setattr(N, "_post_json", fake)
    n = N.Notifier({"dingtalk_webhook": "https://d/hook?access_token=t",
                    "dingtalk_secret": "sec"})
    assert n.send("hi")[0] is True
    assert "timestamp=" in seen["url"]
    assert "sign=" in seen["url"]


# ---------------------------------------------------------------- 配置缺失

def test_missing_webhook(monkeypatch):
    monkeypatch.setattr(N, "_post_json", lambda *a, **k: "{}")
    ok, err = N.Notifier({"notify_channel": "feishu"}).send("hi")
    assert ok is False
    assert "feishu_webhook" in err


# ---------------------------------------------------------------- bot_server 收敛

def test_bot_server_wecom_delegates(monkeypatch):
    """bot_server.send_wecom 现在走 Notifier，不再自己拼 HTTP"""
    seen = {}

    def fake(url, payload, timeout=8):
        seen["url"] = url
        seen["payload"] = payload
        return '{"errcode":0}'

    monkeypatch.setattr(N, "_post_json", fake)
    from core.bot_server import BotServer
    b = BotServer()
    b.set_wecom_webhook("https://q/hook/x")
    assert b.send_wecom("hi") is True
    assert seen["url"] == "https://q/hook/x"
    assert seen["payload"]["msgtype"] == "text"


def test_bot_server_dingtalk_delegates(monkeypatch):
    seen = {}

    def fake(url, payload, timeout=8):
        seen["url"] = url
        return '{"errcode":0}'

    monkeypatch.setattr(N, "_post_json", fake)
    from core.bot_server import BotServer
    b = BotServer()
    b.set_dingtalk_webhook("https://d/hook?access_token=t", secret="sec")
    assert b.send_dingtalk("hi") is True
    assert "sign=" in seen["url"]


def test_bot_server_no_webhook_returns_false():
    from core.bot_server import BotServer
    b = BotServer()
    assert b.send_wecom("hi") is False
    assert b.send_dingtalk("hi") is False


def test_reject_non_http_url(monkeypatch):
    """配置里填了 file:// 之类必须被挡住，不能拿 urlopen 去读本地文件"""
    ok, err = N.Notifier({"feishu_webhook": "file:///C:/Windows/win.ini"}).send("hi")
    assert ok is False
    assert "不安全" in err
