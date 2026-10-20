# -*- coding: utf-8 -*-
"""Capability routing and fallback tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.model_router import (  # noqa: E402
    TaskRequirements, capability_report, is_sufficient, route_model,
    runtime_capabilities,
)


def test_provider_defaults_and_known_matrix_combine():
    caps = runtime_capabilities("openai", "gpt-4o-mini")
    assert caps["tool_calling"] in ("high", "medium")
    assert caps["vision"] is True
    assert capability_report("anthropic", "claude-3-5-sonnet")["context_window"] >= 100000


def test_local_preferred_when_capable():
    route = route_model(local_model="qwen2.5:7b", cloud_model="gpt-4o-mini",
                        provider="openai",
                        requirements=TaskRequirements(needs_tools=True,
                                                      needs_json=True))
    assert route["model"] == "qwen2.5:7b"
    assert route["fallback_chain"] == ["gpt-4o-mini"]


def test_local_failure_falls_back_to_cloud():
    route = route_model(local_model="qwen2.5:7b", cloud_model="gpt-4o-mini",
                        provider="openai", local_failed=True,
                        requirements=TaskRequirements(needs_tools=True))
    assert route["model"] == "gpt-4o-mini"
    assert "local" in route["fallback_reason"].lower()


def test_vision_request_does_not_route_to_non_vision_local():
    route = route_model(local_model="llama3.2:1b", cloud_model="gemini-1.5-flash",
                        provider="gemini",
                        requirements=TaskRequirements(needs_vision=True))
    assert route["model"] == "gemini-1.5-flash"


def test_unknown_model_is_conservative():
    caps = runtime_capabilities("vllm", "private-unknown-model")
    assert caps["tool_calling"] in ("low", "medium")
    ok, why = is_sufficient(caps, TaskRequirements(needs_tools=True))
    assert isinstance(ok, bool)


def test_long_context_falls_back_to_gemini():
    route = route_model(local_model="qwen2.5:7b", cloud_model="gemini-1.5-flash",
                        provider="gemini",
                        requirements=TaskRequirements(min_context=200000))
    assert route["model"] == "gemini-1.5-flash"
