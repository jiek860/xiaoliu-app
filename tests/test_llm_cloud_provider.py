# -*- coding: utf-8 -*-
"""LLMCloud provider integration tests (no network)."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.llm_cloud import LLMCloudMixin  # noqa: E402


class _Resp:
    def __init__(self, data):
        self._data = data
    def json(self):
        return self._data


class _Client(LLMCloudMixin):
    def __init__(self):
        self.trunk = None
        self.base_url = "http://localhost:11434"
        self.calls = []
        self.config = {
            "cloud_provider": "anthropic",
            "cloud_model": "claude-3-5-sonnet-latest",
            "cloud_key": "test-key",
            "cloud_url": "https://api.anthropic.com",
        }
    def _fit_messages(self, msgs):
        return msgs
    def _mask_if_enabled(self, msgs):
        return msgs
    def _track_usage(self, *a, **k):
        return None
    def _post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Resp({"content": [{"type": "text", "text": "ok"}]})


def test_provider_specific_cloud_call():
    c = _Client()
    out = c._try_cloud("hello")
    assert out == "ok"
    assert c.calls
    url, kwargs = c.calls[0]
    assert url.endswith("/v1/messages")
    assert kwargs["headers"]["x-api-key"] == "test-key"


def test_provider_stream_falls_back_to_non_stream():
    c = _Client()
    tokens = []
    out = c._try_cloud_stream("hello", on_token=tokens.append)
    assert out == "ok"
    assert tokens == ["ok"]
