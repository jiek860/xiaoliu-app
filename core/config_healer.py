# -*- coding: utf-8 -*-
"""配置自愈 - 检测配置错误并自动修正，只改数据不改代码"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time, shutil
from core.paths import BASE
class ConfigHealer:
    HEALABLE = {
        "cloud_url_空": {"字段": "cloud_url", "修复": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                         "条件": lambda v: not v or not str(v).startswith("http")},
        "font_size_非法": {"字段": "font_size", "修复": "14px",
                           "条件": lambda v: v not in ("12px","14px","16px","18px")},
    }
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or BASE
        self.cfg_path = os.path.join(self.base, "data", "config.json")
        self.backup_dir = os.path.join(self.base, "data", "config_backup")
        os.makedirs(self.backup_dir, exist_ok=True)
    def check_and_heal(self, auto=True):
        if not os.path.exists(self.cfg_path): return []
        try: cfg = json.load(open(self.cfg_path, encoding="utf-8"))
        except: return self._restore()
        fixes = []
        for name, spec in self.HEALABLE.items():
            v = cfg.get(spec["字段"])
            try:
                if spec["条件"](v): fixes.append({"类型":name, "字段":spec["字段"], "新值":spec["修复"]})
            except Exception as e:
                _x6_swallowed(__name__, e)
                continue
        if fixes and auto:
            self._backup()
            for f in fixes: cfg[f["字段"]] = f["新值"]
            tmp = self.cfg_path + ".tmp"
            json.dump(cfg, open(tmp,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
            os.replace(tmp, self.cfg_path)
        return fixes
    def _backup(self):
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(self.backup_dir, f"config_{ts}.json")
        try: shutil.copy2(self.cfg_path, dst)
        except Exception as e:
            _x6_swallowed(__name__, e)
    def _restore(self):
        try:
            files = sorted(os.listdir(self.backup_dir))
            if not files: return []
            shutil.copy2(os.path.join(self.backup_dir, files[-1]), self.cfg_path)
            return [{"类型":"配置恢复", "备份":files[-1]}]
        except: return []
