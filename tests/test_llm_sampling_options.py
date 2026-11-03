# -*- coding: utf-8 -*-
"""本地/云端请求体里的采样参数与窗口（第 2 批 A1/A3/深度④⑤）。

这里不联网：本地只看 ``_local_options`` 生成的 options，
云端用假的 ``_post`` 抓住请求体断言，确认硬编码 ``temperature: 0.7``
已经被场景参数取代。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.llm_cloud import LLMCloudMixin  # noqa: E402
from core.llm_local import LLMLocalMixin  # noqa: E402


class _Local(LLMLocalMixin):
    def __init__(self, config):
        self.config = config
        self.trunk = None
        self.base_url = "http://localhost:11434"


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def close(self):
        return None


class _StreamResp:
    def __init__(self, lines):
        self._lines = list(lines)

    def iter_lines(self):
        for line in self._lines:
            yield line

    def close(self):
        return None


class _Cloud(LLMCloudMixin):
    def __init__(self, config, stream_lines=None):
        self.trunk = None
        self.base_url = "http://localhost:11434"
        self.config = config
        self.calls = []
        self.stream = _StreamResp(stream_lines or [])

    def _fit_messages(self, msgs):
        return msgs

    def _mask_if_enabled(self, msgs):
        return msgs

    def _track_usage(self, *a, **k):
        self.usage_kind = k.get("kind")

    def _post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if kwargs.get("stream"):
            return self.stream
        # 同时给出 OpenAI 与 Anthropic 两种响应形状，同一套假响应可复用
        return _Resp({
            "choices": [{"message": {"content": "ok"}}],
            "content": [{"type": "text", "text": "ok"}],
        })


def test_local_options_use_window_and_scene_temperature():
    cfg = {"llm_context_window": 32768}
    got = _Local(cfg)._local_options("qwen2.5:7b", "帮我修复这个 bug")
    assert got["num_ctx"] == 12288, "6G 显存撑不住 32768，要按显存收窄"
    assert got["temperature"] == 0.3, "代码场景要更保守"
    chat = _Local(cfg)._local_options("qwen2.5:7b", "今天好累")
    assert chat["temperature"] == 0.7


def test_local_options_honour_user_override_and_seed():
    cfg = {"llm_context_window": 4096, "llm_seed": 42,
           "llm_sampling": {"chat": {"temperature": 0.5}}}
    got = _Local(cfg)._local_options("未知模型", "今天好累")
    assert got["num_ctx"] == 4096
    assert got["temperature"] == 0.5
    assert got["seed"] == 42, "配了 seed 就要透传，评测才能复现"


def test_cloud_request_body_carries_sampling_not_hardcoded():
    cfg = {"cloud_url": "https://api.openai.com/v1",
           "cloud_key": "k", "cloud_model": "gpt-4o-mini"}
    c = _Cloud(cfg)
    assert c._try_cloud("帮我修复这个 bug") == "ok"
    body = c.calls[0][1]["json"]
    assert body["temperature"] == 0.3
    assert "top_p" in body


def test_cloud_stream_request_body_carries_sampling():
    lines = [b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"data: [DONE]"]
    cfg = {"cloud_url": "https://api.openai.com/v1",
           "cloud_key": "k", "cloud_model": "gpt-4o-mini"}
    c = _Cloud(cfg, stream_lines=lines)
    tokens = []
    assert c._try_cloud_stream("今天好累", on_token=tokens.append) == "hi"
    body = c.calls[0][1]["json"]
    assert body["stream"] is True
    assert body["temperature"] == 0.7
    assert tokens == ["hi"]


def test_cloud_provider_drops_unsupported_params():
    """anthropic 不认 frequency_penalty / seed，发过去会被 400。"""
    cfg = {"cloud_provider": "anthropic",
           "cloud_url": "https://api.anthropic.com",
           "cloud_model": "claude-3-5-sonnet-latest", "cloud_key": "k",
           "llm_seed": 42}
    c = _Cloud(cfg)
    assert c._try_cloud("今天好累") == "ok"
    body = c.calls[0][1]["json"]
    assert body["temperature"] == 0.7
    assert "frequency_penalty" not in body
    assert "seed" not in body


def test_cloud_provider_keeps_seed_for_openai_family():
    cfg = {"cloud_provider": "openai", "cloud_url": "https://api.openai.com/v1",
           "cloud_model": "gpt-4o-mini", "cloud_key": "k", "llm_seed": 42}
    c = _Cloud(cfg)
    assert c._try_cloud("今天好累") == "ok"
    assert c.calls[0][1]["json"]["seed"] == 42


def test_cloud_options_falls_back_without_user_text():
    """消息里没有 user 文本（比如只有 system）时不能崩，仍要给出参数。"""
    cfg = {"cloud_url": "https://api.openai.com/v1",
           "cloud_key": "k", "cloud_model": "gpt-4o-mini"}
    c = _Cloud(cfg)
    opts = c._cloud_options("不是 list 也不是 dict")
    assert opts["temperature"] == 0.7
