# -*- coding: utf-8 -*-
"""Feature Flag - 功能开关，关了不用发版

用法：
  from core.feature_flags import is_enabled
  if is_enabled("deep_research"):
      # 显示入口
"""
import json, os

DEFAULTS = {
    "deep_research": True,
    "coder_pro": False,  # 危险操作，默认关
    "trace_view": True,
    "roles": True,
    "web_agent": False,  # 浏览器操作，默认关
    "api_server": False,  # HTTP 服务，默认关
}


def _get_path(base="."):
    return os.path.join(base, "data", "flags.json")


def load_flags(base="."):
    path = _get_path(base)
    if not os.path.exists(path):
        return DEFAULTS.copy()
    try:
        data = json.load(open(path, encoding="utf-8"))
        merged = DEFAULTS.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULTS.copy()


def is_enabled(name, base="."):
    flags = load_flags(base)
    return flags.get(name, True)


def set_flag(name, value, base="."):
    flags = load_flags(base)
    flags[name] = bool(value)
    path = _get_path(base)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(flags, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return True


def list_flags(base="."):
    return load_flags(base)