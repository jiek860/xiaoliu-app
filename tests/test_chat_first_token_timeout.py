# -*- coding: utf-8 -*-
"""批次 2：云端真流式 + 本地首字超时（不干等 120 秒）"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import requests  # noqa: E402

from core.cancel_token import CancelToken  # noqa: E402
from core.llm_client import LLMClient  # noqa: E402
from core.llm_shared import config_seconds  # noqa: E402


class _FakeResp:
    def __init__(self, tokens):
        self._tokens = tokens
        self.closed = False

    def iter_lines(self):
        for tok in self._tokens:
            yield json.dumps({"message": {"content": tok}, "done": False}).encode("utf-8")
        yield json.dumps({"message": {"content": ""}, "done": True}).encode("utf-8")

    def close(self):
        self.closed = True


class _Trunk:
    def __init__(self):
        self.logs = []

    def _log(self, msg):
        self.logs.append(msg)


def _make_client(post, config=None):
    client = LLMClient.__new__(LLMClient)
    client.config = config or {"model_mode": "本地路由", "local_model": "fake-model"}
    client.trunk = _Trunk()
    client.base_url = "http://127.0.0.1:11434"
    client.ollama_down = False
    client._fail_count = 0
    client._model_cooldown = {}
    client._post = post
    chat_calls = []
    client.chat = lambda msgs: chat_calls.append(msgs) or "不该被调用"
    return client, chat_calls


# ---------------------------------------------------------------- 首字超时

def test_local_first_token_timeout_uses_configurable_short_timeout():
    seen = {}

    def post(url, **kwargs):
        seen.update(kwargs)
        raise requests.exceptions.ReadTimeout("no first token")

    client, _ = _make_client(post, {"model_mode": "本地路由",
                                    "local_model": "fake-model",
                                    "本地首字超时": 8})
    client._try_cloud_stream = lambda *a, **k: "云答案"

    assert client.stream_chat("hi", on_token=lambda _t: None) == "云答案"
    assert seen["timeout"] == (5, 8), "本地读超时应改成 (连接, 首字超时) 元组"


def test_local_first_token_timeout_switches_to_cloud_with_cancel_token():
    token = CancelToken()
    captured = {}

    def post(_url, **_kwargs):
        raise requests.exceptions.ReadTimeout("no first token")

    client, chat_calls = _make_client(post)
    got = []

    def cloud(msg, on_token=None, cancel_token=None):
        captured["msg"] = msg
        captured["on_token"] = on_token
        captured["cancel_token"] = cancel_token
        if on_token:
            on_token("云端")
        return "云端"

    client._try_cloud_stream = cloud
    answer = client.stream_chat("讲个故事", on_token=got.append, cancel_token=token)

    assert answer == "云端"
    assert captured["cancel_token"] is token, "切云端时取消令牌必须透传"
    assert got[0].startswith("（本地首字超时"), "应提示用户正在切云端"
    assert got[-1] == "云端"
    assert chat_calls == [], "首字超时后不应再走一次本地非流式重试"
    assert any("首字超时" in line for line in client.trunk.logs)


def test_local_timeout_with_empty_cloud_skips_local_retry():
    def post(_url, **_kwargs):
        raise requests.exceptions.ReadTimeout("no first token")

    client, chat_calls = _make_client(post)
    client._try_cloud_stream = lambda *a, **k: ""

    assert client.stream_chat("hi", on_token=lambda _t: None) == ""
    assert chat_calls == [], "本地已经超时，不应该再阻塞重试本地"


def test_local_timeout_without_on_token_does_not_retry():
    def post(_url, **_kwargs):
        raise requests.exceptions.ReadTimeout("no first token")

    client, chat_calls = _make_client(post)
    assert client.stream_chat("hi") == ""
    assert chat_calls == []


def test_stream_still_works_normally_after_timeout_config():
    resp = _FakeResp(["你", "好"])
    client, _ = _make_client(lambda _url, **_kw: resp,
                             {"model_mode": "本地路由", "local_model": "m",
                              "本地首字超时": "12"})
    got = []
    assert client.stream_chat("hi", on_token=got.append) == "你好"
    assert got == ["你", "好"]


# ---------------------------------------------------------------- 云端模式真流式

def test_cloud_mode_prefers_real_stream_over_one_shot():
    client, _ = _make_client(lambda _url, **_kw: _FakeResp([]))
    client.config["model_mode"] = "云端模型"
    called = {"stream": 0, "once": 0}

    def stream(_msg, on_token=None, cancel_token=None):
        called["stream"] += 1
        if on_token:
            on_token("流式")
        return "流式"

    def once(_msg):
        called["once"] += 1
        return "一次性"

    client._try_cloud_stream = stream
    client._try_cloud = once
    got = []

    assert client.stream_chat("hi", on_token=got.append) == "流式"
    assert got == ["流式"]
    assert called == {"stream": 1, "once": 0}, "云端模式不应再退回一次性调用"


def test_cloud_mode_falls_back_when_stream_unsupported():
    client, _ = _make_client(lambda _url, **_kw: _FakeResp([]))
    client.config["model_mode"] = "云端模型"
    client._try_cloud_stream = lambda *a, **k: ""
    client._try_cloud = lambda _msg: "一次性"
    got = []

    assert client.stream_chat("hi", on_token=got.append) == "一次性"
    assert got == ["一次性"]


def test_cloud_mode_cancel_after_stream_returns_without_tokens():
    token = CancelToken()
    client, _ = _make_client(lambda _url, **_kw: _FakeResp([]))
    client.config["model_mode"] = "云端模型"
    got = []

    def stream(_msg, on_token=None, cancel_token=None):
        cancel_token.cancel()
        return "半段"

    client._try_cloud_stream = stream
    assert client.stream_chat("hi", on_token=got.append, cancel_token=token) == "半段"
    assert got == []


def test_cloud_mode_empty_everywhere_keeps_hint():
    client, _ = _make_client(lambda _url, **_kw: _FakeResp([]))
    client.config["model_mode"] = "云端模型"
    client._try_cloud_stream = lambda *a, **k: ""
    client._try_cloud = lambda _msg: None
    client.chat = lambda _msgs: ""
    got = []

    assert client.stream_chat("hi", on_token=got.append) == ""
    assert got and "云端模型没响应" in got[0]


# ---------------------------------------------------------------- 配置读取

def test_config_seconds_reads_chinese_key_and_clamps():
    cfg = {"本地首字超时": "8"}
    assert config_seconds(cfg, ("本地首字超时", "local_first_token_timeout"), 25) == 8
    assert config_seconds({"本地首字超时": 900}, ("本地首字超时",), 25) == 300
    assert config_seconds({"本地首字超时": 0}, ("本地首字超时",), 25) == 5


def test_config_seconds_falls_back_on_bad_values():
    assert config_seconds({}, ("本地首字超时",), 25) == 25
    assert config_seconds({"本地首字超时": "abc"}, ("本地首字超时",), 25) == 25
    assert config_seconds({"本地首字超时": ""}, ("本地首字超时",), 25) == 25
    assert config_seconds(None, ("本地首字超时",), 25) == 25
    assert config_seconds({"local_first_token_timeout": 30.9},
                          ("本地首字超时", "local_first_token_timeout"), 25) == 30


def test_cloud_stream_timeout_is_configurable(monkeypatch):
    from core.llm_cloud import LLMCloudMixin

    class _C(LLMCloudMixin):
        def __init__(self):
            self.trunk = None
            self.calls = []
            self.config = {"cloud_url": "https://x/chat/completions",
                           "cloud_key": "k", "cloud_model": "m",
                           "云端首字超时": 15}
        def _fit_messages(self, msgs):
            return msgs
        def _mask_if_enabled(self, msgs):
            return msgs
        def _track_usage(self, *a, **k):
            return None
        def _post(self, url, **kwargs):
            self.calls.append(kwargs)
            class _R:
                def iter_lines(self):
                    return [b'data: {"choices":[{"delta":{"content":"ok"}}]}',
                            b"data: [DONE]"]
                def close(self):
                    return None
            return _R()

    c = _C()
    assert c._try_cloud_stream("hi") == "ok"
    assert c.calls[0]["timeout"] == (10, 15)


def test_local_stream_timeout_defaults_to_25_seconds():
    seen = {}

    def post(_url, **kwargs):
        seen.update(kwargs)
        raise requests.exceptions.ReadTimeout("timeout")

    client, _ = _make_client(post)
    client._try_cloud_stream = lambda *a, **k: ""
    client.stream_chat("hi")
    assert seen["timeout"] == (5, 25)
