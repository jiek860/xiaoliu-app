# -*- coding: utf-8 -*-
"""模块健康度 - 记录模块失败次数，连续失败自动禁用"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json
from core.paths import BASE
class ModuleHealth:
    DISABLE_THRESHOLD = 5
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or BASE
        self.path = os.path.join(self.base, "data", "module_health.json")
        self.data = self._load()
    def _load(self):
        if os.path.exists(self.path):
            try: return json.load(open(self.path, encoding="utf-8"))
            except Exception as e:
                _x6_swallowed(__name__, e)
        return {}
    def _save(self):
        try:
            tmp = self.path + ".tmp"
            json.dump(self.data, open(tmp,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            _x6_swallowed(__name__, e)
    def record_failure(self, name, err=""):
        e = self.data.setdefault(name, {"fail_count":0,"disabled":False})
        e["fail_count"] +=1
        e["last_err"] = str(err)[:100]
        if e["fail_count"] >= self.DISABLE_THRESHOLD:
            e["disabled"] = True
        self._save()
    def record_success(self, name):
        if name in self.data:
            self.data[name]["fail_count"] =0
            self.data[name]["disabled"] = False
            self._save()
    def is_disabled(self, name):
        return bool(self.data.get(name,{}).get("disabled", False))
    def enable(self, name):
        if name in self.data:
            self.data[name]["disabled"]=False
            self.data[name]["fail_count"]=0
            self._save()
            return {"ok":True}
        return {"ok":False}
