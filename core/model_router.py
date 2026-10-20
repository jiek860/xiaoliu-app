# -*- coding: utf-8 -*-
"""Task-aware model routing with capability fallback.

The router is deliberately deterministic. It never asks a model to judge its
own capabilities; it uses the static capability matrix, provider defaults and
optional runtime probe results.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.model_capabilities import get_capabilities, route_strategy

LEVEL = {"low": 1, "medium": 2, "high": 3}
PROVIDER_DEFAULTS = {
    "openai": {"tool_calling": "high", "json_mode": "high", "long_context": "high",
               "chinese": "high", "code_edit": "high", "computer_planning": "medium",
               "streaming": True, "vision": True, "context_window": 128000},
    "anthropic": {"tool_calling": "high", "json_mode": "high", "long_context": "high",
                  "chinese": "high", "code_edit": "high", "computer_planning": "medium",
                  "streaming": True, "vision": True, "context_window": 200000},
    "gemini": {"tool_calling": "high", "json_mode": "high", "long_context": "high",
               "chinese": "medium", "code_edit": "medium", "computer_planning": "medium",
               "streaming": True, "vision": True, "context_window": 1000000},
    "openrouter": {"tool_calling": "medium", "json_mode": "medium", "long_context": "medium",
                   "chinese": "medium", "code_edit": "medium", "computer_planning": "low",
                   "streaming": True, "vision": False, "context_window": 32768},
    "lmstudio": {"tool_calling": "medium", "json_mode": "medium", "long_context": "low",
                 "chinese": "medium", "code_edit": "medium", "computer_planning": "low",
                 "streaming": True, "vision": False, "context_window": 8192},
    "llamacpp": {"tool_calling": "low", "json_mode": "medium", "long_context": "low",
                 "chinese": "medium", "code_edit": "medium", "computer_planning": "low",
                 "streaming": True, "vision": False, "context_window": 8192},
    "vllm": {"tool_calling": "medium", "json_mode": "high", "long_context": "medium",
             "chinese": "medium", "code_edit": "medium", "computer_planning": "low",
             "streaming": True, "vision": False, "context_window": 32768},
}


@dataclass
class TaskRequirements:
    needs_tools: bool = False
    needs_json: bool = False
    needs_vision: bool = False
    min_context: int = 0
    prefer_local: bool = True
    complexity: str = "medium"
    metadata: dict = field(default_factory=dict)


def _level_ok(caps, key, minimum="medium"):
    return LEVEL.get(str(caps.get(key) or "low"), 0) >= LEVEL.get(minimum, 2)


def runtime_capabilities(provider, model, overrides=None):
    """Combine static matrix + provider defaults + optional runtime overrides."""
    caps = dict(get_capabilities(model))
    defaults = dict(PROVIDER_DEFAULTS.get(str(provider or "").lower(), {}))
    known_model = bool(caps.get("known"))
    for key, value in defaults.items():
        if not known_model:
            # Unknown models inherit provider-level safety limits and features.
            caps[key] = value
        elif key in ("vision", "streaming", "context_window"):
            if key == "vision" and value is True:
                caps[key] = True
            elif key == "context_window":
                caps[key] = max(int(caps.get(key) or 0), int(value or 0))
        else:
            if LEVEL.get(str(caps.get(key) or "low"), 0) < LEVEL.get(str(value), 0):
                caps[key] = value
    if isinstance(overrides, dict):
        caps.update(overrides)
    caps["provider"] = str(provider or "")
    caps["model"] = str(model or "")
    return caps


def is_sufficient(caps, requirements):
    if requirements.needs_tools and not _level_ok(caps, "tool_calling", "medium"):
        return False, "tool calling unsupported"
    if requirements.needs_json and not _level_ok(caps, "json_mode", "medium"):
        return False, "JSON mode unsupported"
    if requirements.needs_vision and not bool(caps.get("vision")):
        return False, "vision unsupported"
    if requirements.min_context and int(caps.get("context_window") or 0) < requirements.min_context:
        return False, "context window too small"
    return True, ""


def route_model(*, local_model, cloud_model="", provider="", requirements=None,
                local_available=True, local_failed=False, overrides=None):
    """Route a request to local or cloud with an explicit fallback chain."""
    req = requirements or TaskRequirements()
    local_caps = runtime_capabilities("ollama", local_model, overrides)
    cloud_provider = str(provider or "openai")
    cloud_caps = runtime_capabilities(cloud_provider, cloud_model, overrides)
    local_ok, local_why = is_sufficient(local_caps, req)
    cloud_ok, cloud_why = is_sufficient(cloud_caps, req) if cloud_model else (False, "no cloud model")
    reason = ""
    if req.prefer_local and local_available and not local_failed and local_ok:
        chosen, caps, why = local_model, local_caps, "local capabilities satisfy task"
    elif cloud_ok:
        chosen, caps, why = cloud_model, cloud_caps, "cloud fallback satisfies task"
        reason = local_why if not local_ok else "local failed/unavailable"
    elif local_available and local_ok:
        chosen, caps, why = local_model, local_caps, "cloud unavailable; local is best effort"
        reason = cloud_why
    else:
        chosen, caps, why = local_model, local_caps, "no fully capable model; conservative fallback"
        reason = "local: %s; cloud: %s" % (local_why, cloud_why)
    fallback = []
    if chosen == cloud_model and local_model:
        fallback.append(local_model)
    if chosen == local_model and cloud_model:
        fallback.append(cloud_model)
    return {
        "model": chosen,
        "provider": "ollama" if chosen == local_model else cloud_provider,
        "reason": why,
        "fallback_reason": reason,
        "fallback_chain": fallback,
        "capabilities": caps,
        "strategy": route_strategy(chosen),
    }


def capability_report(provider, model, overrides=None):
    caps = runtime_capabilities(provider, model, overrides)
    return {
        "provider": provider, "model": model,
        "tool_calling": bool(_level_ok(caps, "tool_calling", "medium")),
        "json_mode": bool(_level_ok(caps, "json_mode", "medium")),
        "vision": bool(caps.get("vision")),
        "streaming": bool(caps.get("streaming", True)),
        "context_window": int(caps.get("context_window") or 0),
        "chinese": caps.get("chinese", "low"),
        "code_edit": caps.get("code_edit", "low"),
        "computer_planning": caps.get("computer_planning", "low"),
        "raw": caps,
    }
