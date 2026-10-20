# -*- coding: utf-8 -*-
"""Unified model provider adapters.

The application historically assumed one OpenAI-compatible cloud endpoint.
This module normalizes request/response shapes for the major provider families
without making network calls itself, so NetGuard and the existing LLM client
remain the only outbound paths.
"""
from __future__ import annotations

import json
import urllib.parse

PROVIDERS = {
    "openai": {
        "kind": "openai", "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini", "local": False,
        "api_key_key": "cloud_key",
    },
    "openrouter": {
        "kind": "openai", "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-4o-mini", "local": False,
        "api_key_key": "cloud_key",
        "extra_headers": {"HTTP-Referer": "https://github.com/jiek860/xiaoliu-app",
                          "X-Title": "xiao6"},
    },
    "azure_openai": {
        "kind": "azure", "label": "Azure OpenAI",
        "base_url": "", "default_model": "", "local": False,
        "api_key_key": "cloud_key",
    },
    "anthropic": {
        "kind": "anthropic", "label": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-latest", "local": False,
        "api_key_key": "cloud_key",
    },
    "gemini": {
        "kind": "gemini", "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "gemini-1.5-flash", "local": False,
        "api_key_key": "cloud_key",
    },
    "lmstudio": {
        "kind": "openai", "label": "LM Studio",
        "base_url": "http://localhost:1234/v1",
        "default_model": "local-model", "local": True,
        "api_key_key": "",
    },
    "llamacpp": {
        "kind": "openai", "label": "llama.cpp server",
        "base_url": "http://localhost:8080/v1",
        "default_model": "local-model", "local": True,
        "api_key_key": "",
    },
    "vllm": {
        "kind": "openai", "label": "vLLM",
        "base_url": "http://localhost:8000/v1",
        "default_model": "local-model", "local": True,
        "api_key_key": "",
    },
}
ALIASES = {
    "azure": "azure_openai", "azure-openai": "azure_openai",
    "google": "gemini", "google_gemini": "gemini",
    "lm-studio": "lmstudio", "llama.cpp": "llamacpp",
    "llama_cpp": "llamacpp", "openai-compatible": "openai",
}


def normalize_provider(name):
    key = str(name or "").strip().lower()
    return ALIASES.get(key, key)


def provider_names():
    return sorted(PROVIDERS)


def provider_spec(name):
    key = normalize_provider(name)
    return dict(PROVIDERS.get(key) or {})


def _messages(messages):
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    out = []
    for m in messages or []:
        if isinstance(m, dict):
            if m.get("content") is None:
                continue
            out.append({"role": str(m.get("role") or "user"),
                        "content": m.get("content")})
    return out


def _anthropic_messages(messages):
    system = ""
    out = []
    for m in _messages(messages):
        role = m["role"]
        if role == "system":
            system += str(m["content"]) + "\n"
            continue
        out.append({"role": "assistant" if role == "assistant" else "user",
                    "content": str(m["content"])})
    return system.strip(), out


def _gemini_contents(messages):
    out = []
    system = ""
    for m in _messages(messages):
        if m["role"] == "system":
            system += str(m["content"]) + "\n"
            continue
        role = "model" if m["role"] == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": str(m["content"])}]})
    return system.strip(), out


def build_chat_request(provider, model, messages, *, api_key="", base_url="",
                       stream=False, options=None, deployment="",
                       api_version="2024-06-01"):
    """Return ``{url, headers, json, provider, parser}`` for one chat call."""
    key = normalize_provider(provider)
    spec = PROVIDERS.get(key)
    if not spec:
        raise ValueError("unknown provider: %s" % provider)
    kind = spec["kind"]
    model = str(model or spec.get("default_model") or "").strip()
    base = str(base_url or spec.get("base_url") or "").rstrip("/")
    headers = {"Content-Type": "application/json"}
    extra = dict(spec.get("extra_headers") or {})
    headers.update(extra)
    opts = dict(options or {})
    if kind == "openai":
        if not base:
            raise ValueError("provider base_url is required")
        if api_key:
            headers["Authorization"] = "Bearer " + str(api_key)
        body = {"model": model, "messages": _messages(messages), "stream": bool(stream)}
        body.update({k: v for k, v in opts.items() if v is not None})
        return {"url": base + "/chat/completions", "headers": headers,
                "json": body, "provider": key, "kind": kind}
    if kind == "azure":
        if not base or not deployment:
            raise ValueError("Azure OpenAI requires base_url and deployment")
        url = (base + "/openai/deployments/" + urllib.parse.quote(str(deployment)) +
               "/chat/completions?api-version=" + urllib.parse.quote(str(api_version)))
        if api_key:
            headers["api-key"] = str(api_key)
        body = {"model": model or deployment, "messages": _messages(messages),
                "stream": bool(stream)}
        body.update({k: v for k, v in opts.items() if v is not None})
        return {"url": url, "headers": headers, "json": body,
                "provider": key, "kind": kind}
    if kind == "anthropic":
        system, converted = _anthropic_messages(messages)
        if api_key:
            headers["x-api-key"] = str(api_key)
        headers["anthropic-version"] = str(opts.pop("anthropic_version", "2023-06-01"))
        body = {"model": model, "messages": converted,
                "max_tokens": int(opts.pop("max_tokens", 4096)),
                "stream": bool(stream)}
        if system:
            body["system"] = system
        body.update({k: v for k, v in opts.items() if v is not None})
        return {"url": base + "/v1/messages", "headers": headers,
                "json": body, "provider": key, "kind": kind}
    if kind == "gemini":
        if not api_key:
            raise ValueError("Gemini requires api_key")
        url = (base.rstrip("/") + "/models/" + urllib.parse.quote(model) +
               ":generateContent")
        headers["x-goog-api-key"] = str(api_key)
        system, contents = _gemini_contents(messages)
        body = {"contents": contents,
                "generationConfig": {k: v for k, v in opts.items() if v is not None}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return {"url": url, "headers": headers, "json": body,
                "provider": key, "kind": kind}
    raise ValueError("unsupported provider kind: %s" % kind)


def parse_chat_response(provider, data):
    key = normalize_provider(provider)
    spec = PROVIDERS.get(key) or {}
    kind = spec.get("kind")
    if kind in ("openai", "azure"):
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("provider returned no choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "".join(str(x.get("text", "")) if isinstance(x, dict) else str(x)
                              for x in content)
        return str(content)
    if kind == "anthropic":
        parts = data.get("content") or []
        return "".join(str(x.get("text", "")) for x in parts if isinstance(x, dict))
    if kind == "gemini":
        candidates = data.get("candidates") or []
        if not candidates:
            raise ValueError("provider returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        return "".join(str(x.get("text", "")) for x in parts if isinstance(x, dict))
    raise ValueError("unknown provider: %s" % provider)


def parse_stream_chunk(provider, data):
    """Best-effort token parser for streaming response chunks."""
    key = normalize_provider(provider)
    spec = PROVIDERS.get(key) or {}
    kind = spec.get("kind")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return ""
    if kind in ("openai", "azure"):
        choices = data.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("delta") or {}).get("content") or "")
    if kind == "anthropic":
        if data.get("type") == "content_block_delta":
            return str((data.get("delta") or {}).get("text") or "")
        return ""
    if kind == "gemini":
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        return "".join(str(x.get("text", "")) for x in parts if isinstance(x, dict))
    return ""


def config_for_provider(config, provider):
    """Build connector config from the application's flat config dict."""
    config = config or {}
    key = normalize_provider(provider)
    spec = PROVIDERS.get(key) or {}
    return {
        "provider": key,
        "base_url": str(config.get("cloud_url") or spec.get("base_url") or ""),
        "api_key": str(config.get("cloud_key") or ""),
        "model": str(config.get("cloud_model") or spec.get("default_model") or ""),
        "deployment": str(config.get("azure_deployment") or config.get("cloud_model") or ""),
        "api_version": str(config.get("azure_api_version") or "2024-06-01"),
        "local": bool(spec.get("local")),
    }
