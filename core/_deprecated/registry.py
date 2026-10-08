# -*- coding: utf-8 -*-
"""模块注册/懒加载模块 - 从trunk.py拆出来，负责模块注册/加载/卸载"""
import os, sys, time, importlib.util


class ModuleRegistry:
    def __init__(self, trunk):
        self.trunk = trunk
        self.modules = trunk.modules
        self._lazy = trunk._lazy
        self.modules_dir = trunk.modules_dir
        self.base = trunk.base
        self.module_meta = trunk.module_meta
        self.config = trunk.config

    def _log(self, msg):
        self.trunk._log(msg)

    def register(self, name, instance):
        self.modules[name] = instance
        if not hasattr(self.trunk, "_last_use"):
            self.trunk._last_use = {}
        self.trunk._last_use[name] = time.time()

    def has(self, name):
        return name in self.modules or name in self._lazy

    def load(self, name: str) -> any:
        """懒加载模块 v3.0：兼容 2/3 元组"""
        if name in self._lazy and name not in self.modules:
            entry = self._lazy[name]
            if len(entry) >= 3:
                mod_file, cls_name, _cn = entry[0], entry[1], entry[2]
            elif len(entry) == 2:
                mod_file, cls_name = entry[0], entry[1]
            else:
                self._log("懒加载配置错误: %s = %r" % (name, entry))
                return None
            try:
                mod_key = "core." + mod_file
                installed_py = os.path.join(self.modules_dir, mod_file + ".py")
                core_py = os.path.join(self.base, "core", mod_file + ".py")
                if os.path.exists(installed_py):
                    spec = importlib.util.spec_from_file_location(mod_key, installed_py)
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_key] = mod
                    spec.loader.exec_module(mod)
                    src = "插件市场"
                elif os.path.exists(core_py):
                    mod = __import__(mod_key, fromlist=[cls_name])
                    src = "core"
                else:
                    self._log("模块未安装: %s（请到插件市场下载安装）" % name)
                    return None
                cls = getattr(mod, cls_name)
                try:
                    instance = cls(self.trunk)
                except TypeError:
                    instance = cls()
                    if not hasattr(instance, "trunk") or instance.trunk is None:
                        try:
                            instance.trunk = self.trunk
                        except Exception:
                            pass
                self.register(name, instance)
                self._log("加载[%s]: %s" % (src, name))
                if not hasattr(self.trunk, "_mod_load_time"):
                    self.trunk._mod_load_time = {}
                self.trunk._mod_load_time[name] = time.time()
                meta = self.module_meta.get(name)
                if meta and meta.get("needs_model") and "llm" in self.modules:
                    meta["model"] = "已连接"
                    meta["model_name"] = self.config.get("local_model", "?")
                    setattr(instance, "llm", self.modules["llm"])
                return instance
            except Exception as e:
                self._log("加载%s失败: %s" % (name, str(e)[:60]))
                return None
        return self.modules.get(name)

    def assign_model(self, name):
        """给需要模型的模块绑定模型链接"""
        llm = self.modules.get("llm")
        if not llm:
            return {"ok": False, "error": "LLM 未初始化"}
        meta = self.module_meta.get(name, {})
        meta["needs_model"] = True
        meta["model"] = "已连接"
        meta["model_name"] = self.config.get("local_model", "?")
        self.module_meta[name] = meta
        mod = self.modules.get(name)
        if mod is not None:
            setattr(mod, "llm", llm)
            setattr(mod, "_model", llm)
        self._log("模型链接: %s -> %s" % (name, meta["model_name"]))
        return {"ok": True, "module": name, "model": meta["model_name"]}

    def unregister(self, name):
        """卸载模块"""
        mod = self.modules.pop(name, None)
        if mod:
            for m in ["stop", "close", "shutdown", "cleanup"]:
                fn = getattr(mod, m, None)
                if fn:
                    try: fn()
                    except: pass
        return mod
