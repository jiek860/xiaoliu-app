# -*- coding: utf-8 -*-
"""Model capability matrix and conservative routing decisions."""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(BASE, "config", "model_capabilities.json")
LEVELS = {"low": 1, "medium": 2, "high": 3}

_DEFAULTS = {
    "tool_calling": "low", "json_mode": "low", "long_context": "low",
    "chinese": "medium", "code_edit": "low", "computer_planning": "low",
    "streaming": True, "vision": False, "context_window": 8192,
}


def _load(path=None):
    try:
        with open(path or DEFAULT_PATH, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"models": [], "defaults": dict(_DEFAULTS), "routes": {}}


def _match(model_name, model):
    name = str(model_name or "").lower()
    return any(str(alias).lower() in name for alias in model.get("aliases") or [])


def get_capabilities(model_name, path=None):
    data = _load(path)
    caps = dict(data.get("defaults") or _DEFAULTS)
    matched = None
    for model in data.get("models") or []:
        if _match(model_name, model):
            matched = model
            break
    if matched:
        caps.update({k: v for k, v in matched.items()
                     if k not in ("id", "aliases")})
        caps["model_id"] = matched.get("id")
        caps["known"] = True
    else:
        caps["model_id"] = "unknown"
        caps["known"] = False
        # Conservative fallback: never assume tool/JSON support for an
        # unregistered model.
        caps["tool_calling"] = "low"
        caps["json_mode"] = "low"
        caps["context_window"] = min(int(caps.get("context_window") or 8192), 8192)
    return caps


def _enabled(caps, key, minimum="medium"):
    return LEVELS.get(str(caps.get(key) or "low"), 0) >= LEVELS[minimum]


def route_strategy(model_name, *, local_failed=False, path=None):
    data = _load(path)
    caps = get_capabilities(model_name, path=path)
    routes = data.get("routes") or {}
    fallback = routes.get("default_fallback") or ""
    if local_failed:
        fallback = routes.get("cloud_fallback") or fallback
    return {
        "model": model_name,
        "known": bool(caps.get("known")),
        "tool_calling": _enabled(caps, "tool_calling"),
        "json_mode": _enabled(caps, "json_mode"),
        "streaming": bool(caps.get("streaming", True)),
        "vision": bool(caps.get("vision", False)),
        "max_context": int(caps.get("context_window") or 8192),
        "conservative_prompt": not bool(caps.get("known")),
        "fallback_model": fallback,
        "capabilities": caps,
    }


def cap_bool(model_name, capability, minimum="medium", path=None):
    return _enabled(get_capabilities(model_name, path=path), capability, minimum)
