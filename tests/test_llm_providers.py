# -*- coding: utf-8 -*-
"""Unified provider request/response adapter tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.llm_providers import (  # noqa: E402
    build_chat_request, config_for_provider, parse_chat_response,
    parse_stream_chunk, provider_names, provider_spec,
)


def test_provider_list_contains_required_families():
    names = set(provider_names())
    assert {"openai", "anthropic", "gemini", "openrouter", "azure_openai",
            "lmstudio", "llamacpp", "vllm"}.issubset(names)
    assert provider_spec("lm-studio")["kind"] == "openai"
    assert provider_spec("azure")["kind"] == "azure"


def test_openai_and_local_compatible_request():
    req = build_chat_request("openai", "gpt-4o-mini",
                             [{"role": "user", "content": "hi"}], api_key="k")
    assert req["url"].endswith("/chat/completions")
    assert req["headers"]["Authorization"] == "Bearer k"
    assert req["json"]["model"] == "gpt-4o-mini"
    lm = build_chat_request("lmstudio", "local-model",
                            [{"role": "user", "content": "hi"}])
    assert lm["url"].startswith("http://localhost:1234/")
    assert "Authorization" not in lm["headers"]


def test_anthropic_request_and_response():
    req = build_chat_request("anthropic", "claude-3-5-sonnet-latest",
                             [{"role": "system", "content": "rules"},
                              {"role": "user", "content": "hi"}], api_key="k")
    assert req["url"].endswith("/v1/messages")
    assert req["headers"]["x-api-key"] == "k"
    assert req["json"]["system"] == "rules"
    assert req["json"]["messages"][0]["role"] == "user"
    out = parse_chat_response("anthropic", {"content": [{"type": "text", "text": "ok"}]})
    assert out == "ok"


def test_gemini_request_and_response():
    req = build_chat_request("gemini", "gemini-1.5-flash",
                             [{"role": "user", "content": "hi"}], api_key="g")
    assert "generateContent" in req["url"]
    assert req["json"]["contents"][0]["parts"][0]["text"] == "hi"
    out = parse_chat_response("gemini", {"candidates": [{"content": {
        "parts": [{"text": "hello"}]}}]})
    assert out == "hello"


def test_azure_request_shape():
    req = build_chat_request("azure_openai", "gpt-4o",
                             [{"role": "user", "content": "hi"}], api_key="k",
                             base_url="https://example.openai.azure.com",
                             deployment="my-deploy")
    assert "/openai/deployments/my-deploy/chat/completions" in req["url"]
    assert "api-version=" in req["url"]
    assert req["headers"]["api-key"] == "k"


def test_openai_response_parser_and_stream_chunk():
    data = {"choices": [{"message": {"content": "hello"}}]}
    assert parse_chat_response("openrouter", data) == "hello"
    chunk = {"choices": [{"delta": {"content": "he"}}]}
    assert parse_stream_chunk("openai", chunk) == "he"


def test_provider_config_from_flat_config():
    cfg = config_for_provider({"cloud_url": "https://x/v1", "cloud_key": "k",
                               "cloud_model": "m"}, "openai")
    assert cfg["provider"] == "openai"
    assert cfg["base_url"] == "https://x/v1"
    assert cfg["model"] == "m"


def test_unknown_provider_fails_closed():
    try:
        build_chat_request("nope", "m", "hi", api_key="k")
        assert False
    except ValueError:
        pass
