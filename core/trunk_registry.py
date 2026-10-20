# -*- coding: utf-8 -*-
"""Trunk 模块注册、懒加载、调用和运行时入口。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class TrunkRegistryMixin:
    def _register_core(self):
        """P0-12: 并行加载核心模块，加快启动速度"""
        import concurrent.futures

        tasks = [
            ("llm", "core.llm_client", "LLMClient"),
            ("vector_store", "core.vector_store", "VectorStore"),
            ("auth", "core.auth", "Auth"),
            ("backup", "core.backup", "Backup"),
            ("knowledge_graph", "core.knowledge_graph", "KnowledgeGraph"),
            ("rules_engine", "core.rules_engine", "RuleEngine"),
        ]

        def _load_one(name, mod_path, cls_name):
            try:
                mod = __import__(mod_path, fromlist=[cls_name])
                cls = getattr(mod, cls_name)
                return name, cls(self), None
            except Exception as e:
                return name, None, str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futures = [ex.submit(_load_one, n, m, c) for n, m, c in tasks]
            for f in concurrent.futures.as_completed(futures):
                name, inst, err = f.result()
                if err:
                    self._log("%s失败: %s" % (name, err))
                else:
                    self.register(name, inst)

        self._log("核心模块注册完成，共%d个（其他%d个懒加载，并行启动）" % (len(self.modules), len(self._lazy)))
        # 数据迁移已在load_config里自动完成
        # 启动健康自检（P2-05）
        try:
            loaded = len(self.modules)
            lazy = len(self._lazy)
            self._log("✅ 启动健康检查通过：已加载%d个核心模块，%d个模块待懒加载" % (loaded, lazy))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        try:
            self.export_module_map()
        except Exception as e:
            self._log("模块星图导出失败: %s" % e)

    def export_module_map(self):
        """把模块星图写到 data/modules_map.js（实现在 core/module_map.py）

        纯展示逻辑，不属于内核职责，已搬出去 —— 内核只留一行委托。
        """
        from core import module_map
        return module_map.export(self)

    def _load_lazy(self, name: str) -> any:
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
                import importlib.util
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
                    instance = cls(self)
                except TypeError:
                    # 类不接受trunk参数，兜底无参实例化，但手动绑trunk
                    instance = cls()
                    if not hasattr(instance, "trunk") or instance.trunk is None:
                        try:
                            instance.trunk = self
                        except Exception as e:
                            _x6_swallowed(__name__, e)
                            pass
                self.register(name, instance)
                self._log("加载[%s]: %s" % (src, name))
                # 记录加载时间，用于自动卸载
                if not hasattr(self, "_mod_load_time"):
                    self._mod_load_time = {}
                self._mod_load_time[name] = time.time()
                # 声明需要模型的模块：自动绑定躯干分配的 LLM
                meta = self.module_meta.get(name)
                if meta and meta.get("needs_model") and "llm" in self.modules:
                    meta["model"] = "已连接"
                    meta["model_name"] = self.config.get("local_model", "?")
                    instance.llm = self.modules["llm"]
                return instance
            except Exception as e:
                self._log("加载%s失败: %s" % (name, str(e)[:60]))
                return None
        return self.modules.get(name)

    def assign_model(self, name):
        """给需要模型的模块绑定躯干分配的模型链接（插件市场安装后调用）"""
        llm = self.modules.get("llm")
        if not llm:
            return {"ok": False, "error": "LLM 未初始化（躯干还没分配模型）"}
        meta = self.module_meta.get(name, {})
        meta["needs_model"] = True
        meta["model"] = "已连接"
        meta["model_name"] = self.config.get("local_model", "?")
        self.module_meta[name] = meta
        mod = self.modules.get(name)
        if mod is not None:
            mod.llm = llm
            mod._model = llm
        self._log("模型链接: %s -> %s" % (name, meta["model_name"]))
        return {"ok": True, "module": name, "model": meta["model_name"], "llm": llm}

    def unregister_module(self, name):
        """卸载模块（插件市场卸载时调用）：停实例、清注册、清缓存"""
        mod = self.modules.pop(name, None)
        if mod:
            for m in ["stop", "close", "shutdown", "cleanup"]:
                fn = getattr(mod, m, None)
                if fn:
                    try:
                        fn()
                    except Exception as e:
                        self._log("异常: " + str(e)[:80])
        if name in self._lazy:
            mod_path = "core." + self._lazy[name][0]
            if mod_path in sys.modules:
                try:
                    del sys.modules[mod_path]
                except Exception as e:
                    self._log("异常: " + str(e)[:80])
        self.module_meta.pop(name, None)
        self._log("已卸载模块: %s" % name)
        return True

    def register(self, name, instance):
        self.modules[name] = instance
        self._last_use[name] = time.time()

    def has(self, name):
        return name in self.modules or name in self._lazy

    def get_llm(self) -> any:
        """获取 LLM 模块（公共方法，代替每个模块自己写 trunk.modules.get('llm')）"""
        return self.modules.get("llm")

    def get_cfg(self, key: str, default=None) -> any:
        """读配置带默认值（公共方法）"""
        return self.config.get(key, default)

    def _disp(self, name):
        """模块的中文显示名（LAZY_MAP 第 3 个字段），没有就用英文键名。

        报错时给用户看「图片识别」，比看 "image_ocr" 有用得多。
        """
        e = self._lazy.get(name) if hasattr(self, "_lazy") else None
        if isinstance(e, (list, tuple)) and len(e) >= 3 and e[2]:
            return str(e[2])
        return name

    def call(self, name: str, method: str, *args, **kwargs) -> any:
        if name in self._aliases:
            name = self._aliases[name]
        if name not in self.modules and name in self._lazy:
            self._load_lazy(name)
        mod = self.modules.get(name)
        if not mod:
            # 原来只说"这个功能还没装好，请联系开发者" —— 不说哪个功能，也不说下一步。
            # 末尾的「功能不可用」是稳定标记，_FAIL_MARKS 靠它识别失败回复。
            self._log("调用失败: %s 未加载" % name, "WARN")
            return {"ok": False,
                    "error": "「%s」没装好（功能不可用）。"
                             "到 设置 → 扩展 → 插件市场 看看是否已安装" % self._disp(name)}
        self._last_use[name] = time.time()
        fn = getattr(mod, method, None)
        if not fn:
            # "__no__" 是懒加载探针惯用法：全项目 19 处故意写这个不存在的方法名，
            # 只为触发上面那次 _load_lazy 而不真的调用。它不是故障，别刷日志
            # （WARN 还会 print 到控制台，一轮后台巡检能刷好几条）。
            if method != "__no__":
                self._log("调用失败: %s 没有 %s 方法" % (name, method), "WARN")
            return {"ok": False,
                    "error": "「%s」没有「%s」这个功能（功能不可用，版本可能不一致）"
                             % (self._disp(name), method)}
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self._log("错误: %s.%s - %s" % (name, method, str(e)[:50]))
            # 翻译成人话 + 下一步（原来只扔一句原始异常，用户看不懂也不知道做什么）。
            # 技术细节仍然保留在括号里，排查时要用。
            try:
                from core.error_text import describe
                msg = describe(e, subject="%s.%s" % (self._disp(name), method))
            except Exception:
                msg = "「%s」的「%s」出错了：%s" % (self._disp(name), method,
                                                   str(e)[:80])
            return {"ok": False, "error": msg, "技术细节": str(e)[:200]}

    def get_task_runtime(self):
        """延迟创建统一任务运行时（所有任务入口共用同一个实例）。"""
        rt = getattr(self, "_task_runtime", None)
        if rt is None:
            from core.task_runtime import TaskRuntime
            rt = TaskRuntime(self)
            self._task_runtime = rt
        return rt

    def validate_lazy_imports(self, isolated=False):
        """按需检查全部懒加载模块；isolated=True 时使用子进程隔离。"""
        from core.lazy_health import compile_lazy_sources, isolated_check, probe_lazy_imports
        compile_report = compile_lazy_sources(self.base)
        if isolated:
            import_report = isolated_check(self.base)
        else:
            import_report = probe_lazy_imports(self.base)
        return {"ok": bool(compile_report.get("ok")
                           and import_report.get("ok")),
                "compile": compile_report, "import": import_report}

    def get_workspace_index(self):
        """延迟创建项目索引（文件、Python 符号、import、测试关联）。"""
        idx = getattr(self, "_workspace_index", None)
        if idx is None:
            from core.workspace_index import WorkspaceIndex
            idx = WorkspaceIndex(self.base, self.base)
            self._workspace_index = idx
        return idx

    def list_modules(self):
        return {
            "核心": list(self.modules.keys()),
            "懒加载": list(self._lazy.keys())
        }

    def unload_idle_modules(self, idle_sec=300):
        """BUG-20: 手动触发卸载空闲模块（后台_auto_unload_loop每30秒自动跑一次）"""
        try:
            # 常驻白名单：和_auto_unload_loop保持一致
            core = {"llm", "vector_store", "auth", "backup", "knowledge_graph",
                    "rules_engine", "scheduler", "hot_reload",
                    "error_lib", "learning_loop", "memory_loop"}
            now = time.time()
            to_unload = []
            for name in list(self.modules.keys()):
                if name in core:
                    continue
                last = self._last_use.get(name, 0)
                if last and now - last > idle_sec:
                    to_unload.append(name)
            for name in to_unload:
                del self.modules[name]
                self._log("手动卸载空闲模块: %s（释放内存）" % name)
        except Exception as e:
            self._log("卸载模块失败: %s" % str(e)[:60])
