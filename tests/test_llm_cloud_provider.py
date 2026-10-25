# -*- coding: utf-8 -*-
"""LLMCloud provider integration tests (no network)."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.cancel_token import CancelToken  # noqa: E402
from core.llm_cloud import LLMCloudMixin  # noqa: E402


class _Resp:
    def __init__(self, data):
        self._data = data
    def json(self):
        return self._data


class _StreamResp:
    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def iter_lines(self):
        for line in self._lines:
            yield line

    def close(self):
        self.closed = True


class _Logger:
    def __init__(self):
        self.lines = []

    def _log(self, msg):
        self.lines.append(msg)


class _Client(LLMCloudMixin):
    def __init__(self, provider="anthropic", stream_lines=None):
        self.trunk = None
        self.base_url = "http://localhost:11434"
        self.calls = []
        self.stream = _StreamResp(stream_lines or [])
        self.config = {
            "cloud_provider": provider,
            "cloud_model": "claude-3-5-sonnet-latest",
            "cloud_key": "test-key",
            "cloud_url": "https://api.anthropic.com",
        }
    def _fit_messages(self, msgs):
        return msgs
    def _mask_if_enabled(self, msgs):
        return msgs
    def _track_usage(self, *a, **k):
        self.usage = k.get("kind")
    def _post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if kwargs.get("stream"):
            return self.stream
        return _Resp({"content": [{"type": "text", "text": "ok"}]})


def test_provider_specific_cloud_call():
    c = _Client()
    out = c._try_cloud("hello")
    assert out == "ok"
    assert c.calls
    url, kwargs = c.calls[0]
    assert url.endswith("/v1/messages")
    assert kwargs["headers"]["x-api-key"] == "test-key"


def test_provider_stream_really_streams_and_parses_anthropic_sse():
    """配置了 cloud_provider 也必须走真流式，而不是退回一次性调用。"""
    lines = [
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"\xe4\xbd\xa0"}}',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"\xe5\xa5\xbd"}}',
        b"data: [DONE]",
    ]
    c = _Client(stream_lines=lines)
    tokens = []

    out = c._try_cloud_stream("hello", on_token=tokens.append)

    assert out == "你好"
    assert tokens == ["你", "好"], "每个 SSE 分块都应实时回调，而不是最后整段刷出"
    url, kwargs = c.calls[0]
    assert url.endswith("/v1/messages")
    assert kwargs["stream"] is True
    assert kwargs["json"]["stream"] is True
    assert c.stream.closed is True
    assert c.usage == "cloud_model_stream"


def test_provider_stream_openai_compatible_delta():
    lines = [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}',
        b'data: [DONE]',
    ]
    c = _Client(provider="openai", stream_lines=lines)
    c.config["cloud_url"] = "https://api.openai.com/v1"
    tokens = []

    assert c._try_cloud_stream("hello", on_token=tokens.append) == "hi"
    assert tokens == ["hi"]
    assert c.calls[0][0].endswith("/chat/completions")


def test_provider_stream_cancel_returns_partial_and_closes_response():
    token = CancelToken()
    lines = [
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"\xe4\xbd\xa0"}}',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"\xe5\xa5\xbd"}}',
    ]
    c = _Client(stream_lines=lines)
    tokens = []

    out = c._try_cloud_stream(
        "hello", on_token=lambda t: (tokens.append(t), token.cancel())[0],
        cancel_token=token)

    assert out == "你", "取消后应保留已收到的内容"
    assert tokens == ["你"], "取消后不应继续回调"
    assert c.stream.closed is True, "取消后必须关闭流响应"


def test_provider_stream_error_returns_empty_and_logs():
    class _Boom(_Client):
        def _post(self, url, **kwargs):
            raise RuntimeError("network down")

    c = _Boom()
    c.trunk = _Logger()
    assert c._try_cloud_stream("hello") == ""
    assert any("云端流式失败" in line for line in c.trunk.lines)


def test_stream_cancelled_before_start_skips_request():
    token = CancelToken()
    token.cancel()
    c = _Client(stream_lines=[])
    assert c._try_cloud_stream("hello", cancel_token=token) == ""
    assert c.calls == []


def test_stream_transport_error_after_cancel_is_not_logged_as_failure():
    token = CancelToken()

    class _Stream:
        def iter_lines(self):
            token.cancel()
            raise ValueError("socket closed")

        def close(self):
            return None

    class _Boom(_Client):
        def _post(self, url, **kwargs):
            return _Stream()

    c = _Boom()
    c.trunk = _Logger()
    assert c._try_cloud_stream("hello", cancel_token=token) == ""
    assert c.trunk.lines == [], "取消引起的传输异常不应记成云端失败"


def test_stream_without_cloud_config_returns_empty():
    c = _Client()
    c.config = {"cloud_provider": "", "cloud_url": "", "cloud_key": ""}
    assert c._try_cloud_stream("hello") == ""
    assert c.calls == []


def test_gemini_stream_uses_stream_generate_content():
    from core.llm_providers import build_chat_request

    req = build_chat_request("gemini", "gemini-1.5-flash", "hi",
                             api_key="k", stream=True)
    assert ":streamGenerateContent" in req["url"]
    assert "alt=sse" in req["url"]
