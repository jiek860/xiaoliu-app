# -*- coding: utf-8 -*-
"""Model capability matrix tests."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.model_capabilities import (  # noqa: E402
    cap_bool, get_capabilities, route_strategy,
)


def test_known_models_get_capabilities():
    q = get_capabilities("qwen2.5:7b")
    assert q["model_id"] == "qwen"
    assert q["tool_calling"] == "high"
    assert cap_bool("qwen2.5:7b", "json_mode") is True
    d = get_capabilities("deepseek-chat")
    assert d["context_window"] >= 32768


def test_unknown_model_is_conservative():
    caps = get_capabilities("totally-unregistered-model")
    assert caps["known"] is False
    assert caps["tool_calling"] == "low"
    strategy = route_strategy("totally-unregistered-model")
    assert strategy["tool_calling"] is False
    assert strategy["json_mode"] is False
    assert strategy["conservative_prompt"] is True
    assert strategy["max_context"] <= 8192


def test_local_failure_routes_to_cloud_fallback():
    strategy = route_strategy("local-7b", local_failed=True)
    assert strategy["fallback_model"] == "deepseek"
