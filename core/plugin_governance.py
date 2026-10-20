# -*- coding: utf-8 -*-
"""插件治理：权限估计、信任等级和安装历史。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import re
import time

_PERM_RULES = [
    ("execute", re.compile(r"\b(subprocess|Popen|os\.system|exec\(|eval\()\b")),
    ("network", re.compile(r"\b(requests\.|urllib\.|socket\.|http\.client)\b")),
    ("filesystem", re.compile(r"\b(open\(|shutil\.|os\.remove|os\.unlink|rmtree)\b")),
    ("ui_control", re.compile(r"\b(pyautogui|win32gui|uiautomation)\b")),
    ("secrets", re.compile(r"\b(key|token|password|secret)\b", re.I)),
]


def analyze_source(text):
    text = str(text or "")
    perms = [name for name, rx in _PERM_RULES if rx.search(text)]
    return {"permissions": perms,
            "risk": "high" if "execute" in perms else
                    ("medium" if perms else "low")}


def trust_level(meta):
    meta = meta or {}
    if meta.get("signature"):
        return "official_signed"
    if meta.get("sha256"):
        return "hash_only"
    return "untrusted"


class PluginGovernance:
    def __init__(self, base):
        self.base = base
        self.path = os.path.join(base, "data", "plugin_install_history.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def inspect(self, source="", meta=None):
        info = analyze_source(source)
        info["trust"] = trust_level(meta)
        return info

    def record(self, name, *, source="", trust="", permissions=None,
               version="", sha256=""):
        rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "name": name, "source": source, "trust": trust,
               "permissions": list(permissions or []),
               "version": version, "sha256": sha256}
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        return rec

    def history(self, limit=100):
        try:
            lines = open(self.path, encoding="utf-8").read().splitlines()[-limit:]
            return [json.loads(x) for x in lines if x.strip()]
        except Exception:
            return []
