# -*- coding: utf-8 -*-
"""模型注册表和健康检查。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json
import os
import time


CATALOG = [
    {"name": "qwen2.5:3b", "context": 32768, "capabilities": ["chat", "tool"],
     "vram_gb": 3, "cost": 0.0},
    {"name": "qwen2.5:7b", "context": 32768, "capabilities": ["chat", "tool"],
     "vram_gb": 6, "cost": 0.0},
    {"name": "qwen2.5-coder:7b", "context": 32768,
     "capabilities": ["code", "tool"], "vram_gb": 6, "cost": 0.0},
    {"name": "qwen3-vl:8b", "context": 32768,
     "capabilities": ["chat", "vision", "tool"], "vram_gb": 8, "cost": 0.0},
    {"name": "glm-4-flash", "context": 128000, "capabilities": ["chat", "tool"],
     "vram_gb": 0, "cost": 0.001},
    {"name": "deepseek-chat", "context": 64000,
     "capabilities": ["chat", "code", "tool"], "vram_gb": 0, "cost": 0.001},
]


class ModelRegistry:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "model_registry.json")
        self.items = self._load()

    def _load(self):
        try:
            d = json.load(open(self.path, encoding="utf-8"))
            return list(d.get("models") or [])
        except Exception:
            return []

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            json.dump({"models": self.items}, open(tmp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def register(self, name, *, kind="local", provider="", context=4096,
                 capabilities=None, cost_per_1k=0.0):
        rec = {"name": str(name), "kind": kind, "provider": provider,
               "context": int(context), "capabilities": list(capabilities or []),
               "cost_per_1k": float(cost_per_1k), "updated_at": time.time()}
        self.items = [x for x in self.items if x.get("name") != name] + [rec]
        self._save()
        return rec

    def list(self):
        return list(self.items)

    @staticmethod
    def catalog():
        return [dict(x) for x in CATALOG]

    @staticmethod
    def hardware_profile():
        out = {"ram_gb": 0, "gpu": [], "recommended": []}
        try:
            import psutil
            out["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception as e:  # 静默是故意的 - psutil 缺失时硬件信息留空
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader"], capture_output=True, text=True,
                timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in (r.stdout or "").splitlines():
                if line.strip():
                    out["gpu"].append(line.strip())
        except Exception as e:  # 静默是故意的 - 没有 NVIDIA GPU 是正常状态
            _x6_swallowed(__name__, e, "best-effort fallback")
        ram = out["ram_gb"]
        for m in CATALOG:
            need = m.get("vram_gb", 0)
            if need == 0 or not out["gpu"] and need <= max(0, ram - 4):
                out["recommended"].append(m["name"])
        return out

    def route_plan(self):
        cfg = getattr(self.trunk, "config", {}) or {}
        return {
            "mode": cfg.get("model_mode", "本地路由"),
            "local": [cfg.get("local_model", ""),
                      cfg.get("small_model", "")],
            "cloud": [cfg.get("cloud_model", "")],
            "fallback": [cfg.get("local_model", ""),
                         cfg.get("small_model", ""),
                         cfg.get("cloud_model", "")],
        }

    def health(self, name):
        for m in self.items:
            if m.get("name") != name:
                continue
            if m.get("kind") == "local":
                return self._probe_ollama(name)
            return {"ok": bool(m.get("provider")), "kind": "cloud"}
        return {"ok": False, "error": "模型未登记"}

    def _probe_ollama(self, name):
        try:
            import urllib.request
            from core.net_guard import get_net_guard
            url = (getattr(self.trunk, "config", {}) or {}).get(
                "ollama_url", "http://localhost:11434").rstrip("/") + "/api/tags"
            d = get_net_guard(self.trunk).check(
                url, module="model_registry", purpose="local_model")
            if not d.get("allow"):
                return {"ok": False, "error": d.get("reason")}
            data = json.loads(urllib.request.urlopen(url, timeout=3).read())
            names = [x.get("name") for x in data.get("models", [])]
            return {"ok": name in names, "models": names}
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}
