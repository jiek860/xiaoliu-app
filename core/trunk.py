# -*- coding: utf-8 -*-
"""微核躯干 v12.0
核心职责：
1. 模块注册与懒加载（_load_lazy）
2. 回复主流程（reply）：意图识别→检索→工具调用→LLM→闭环
3. 日志与崩溃兜底
4. 配置读取与保存
"""
import os, json, time, threading, sys, traceback
from datetime import datetime


class Trunk:
    """融合式躯干：核心能力直接内置，扩展模块注册调用"""

    def __init__(self):
        # 进程起点：给深度自检报启动耗时用（见 _deep_check）
        import time as _tstart
        self._process_start = _tstart.time()
        # 打包后（PyInstaller frozen）：可写数据放 exe 旁边，只读资源放 _MEIPASS
        if getattr(sys, 'frozen', False):
            self.base = os.path.dirname(sys.executable)
            self.res_base = getattr(sys, '_MEIPASS', self.base)
        else:
            self.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.res_base = self.base
        self.data_dir = os.path.join(self.base, 'data')
        self.log_dir = os.path.join(self.data_dir, 'logs')
        self.kb_dir = os.path.join(self.data_dir, 'knowledge_docs')
        for d in [self.log_dir, self.kb_dir]:
            os.makedirs(d, exist_ok=True)

        self.log_path = os.path.join(self.log_dir, 'trunk.log')
        self.crash_path = os.path.join(self.log_dir, 'crashes.log')
        self.config_path = os.path.join(self.data_dir, 'config.json')
        # 注意：这里**不**自动装 sys.excepthook。
        # 原来在 __init__ 里直接 sys.excepthook = self._global_excepthook，
        # 后果是任何创建了 Trunk 的东西 —— 测试、脚本、tools/ 下的工具 ——
        # 一崩就往用户真实的 data/logs/crashes.log 里写，
        # 还会把深度自检的"今天N条崩溃"顶上去、白扣健康分（实际发生过：
        # 我自己的几个临时验证脚本写进去 3 条，健康分从 100 掉到 80）。
        # 需要的话由程序入口显式调 install_crash_hook()：
        # run.py / gui/app_pyqt.py 本来就各自装了钩子，run_server.py 调下面这个方法。
        self._owns_excepthook = False

        self.modules = {}
        self._lock = threading.Lock()
        self._last_use = {}
        self.stats = {"calls": 0, "errors": 0, "module_stats": {}}
        self._route_cache = {}
        # P2-5: 性能监控
        try:
            from core.perf import PerfMonitor
            self.perf = PerfMonitor()
        except Exception:
            self.perf = None
        # v12: 模块元信息（插件市场安装后写入）+ 已安装模块目录
        self.module_meta = {}
        self.modules_dir = os.path.join(self.base, "modules", "installed")
        os.makedirs(self.modules_dir, exist_ok=True)
        self.config = self._load_config()
        self.memory_path = os.path.join(self.data_dir, 'memory.json')
        self.current_user = None
        self.kb_index = os.path.join(self.kb_dir, '_index.json')
        self.memory = self._load_memory()
        self.kb_items = self._load_kb()

        # 懒加载映射表（从配置文件导入）
        from core.lazy_config import LAZY_MAP
        self._lazy = dict(LAZY_MAP)

        # 别名
        # 指向真身，老插件调 web_learner 仍然能用（proactive_learner 早已改名成
        # active_learning，直接删这条会让老插件静默失效）。
        # 下面那批 a->a 的自映射已删除：call() 里白查一次字典，行为完全一致。
        self._aliases = {
            "errors": "error_lib",
            "enhanced_memory": "vector_store",
            "file_reader": "file_upload",
            "web_learner": "active_learning",
            "auto_fixer": "error_lib",
            "llm_client": "llm",
        }

        self._register_core()
        # P0-4: 后台任务单线程队列，防止连续发消息起多个线程抢资源
        import queue as _q
        self._bg_queue = _q.Queue()
        self._bg_worker = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_worker.start()
        # 空闲任务队列：反思/记忆闭环要调模型，不能在用户连续聊天时插队。
        # 不能放在 _bg_loop 里 sleep —— 那是单线程队列，会把记忆入库一起堵住。
        self._idle_queue = _q.Queue()
        threading.Thread(target=self._idle_worker, daemon=True).start()
        threading.Thread(target=self._auto_unload_loop, daemon=True).start()
        # 后台服务丢线程，不阻塞 UI 启动
        threading.Thread(target=self._start_background, daemon=True).start()
        # 启动时自动备份一次（走 core/backup.py，带节流，见 _auto_backup）
        threading.Thread(target=self._auto_backup, daemon=True).start()
        # 性能优化：Ollama 预热 + 向量库预加载
        threading.Thread(target=self._warmup, daemon=True).start()
        # 尝试初始化 pipeline；初始化就失败的话只能一直走 legacy
        self._use_pipeline = True
        # pipeline 出错后的冷却重试状态（见 _reply_inner / _pipeline_failed）
        self._pipeline_fail_count = 0     # 连续失败次数，成功一次就清零
        self._pipeline_retry_at = 0.0     # 早于这个时间点不重试 pipeline
        try:
            from core.pipeline import ReplyPipeline
            self._pipeline = ReplyPipeline(self)
            self._log("Pipeline 初始化成功")
        except Exception as e:
            self._use_pipeline = False
            self._pipeline = None
            self._log(f"Pipeline 初始化失败，使用旧流程: {e}")
        # 后台自我改进组件（全try包裹，坏了不影响主程序）
        try:
            from core.config_healer import ConfigHealer
            fixes = ConfigHealer(self).check_and_heal()
            if fixes: self._log(f"配置自愈完成，修复{len(fixes)}项")
        except Exception as e: pass
        try:
            from core.module_health import ModuleHealth
            disabled = ModuleHealth(self).disabled_modules()
            if disabled: self._log(f"已自动禁用坏模块: {disabled}")
        except: pass
        self._log("躯干启动")

    def _warmup(self):
        """预热：后台加载 Ollama 模型 + 向量库，不阻塞启动"""
        try:
            time.sleep(2)
            try:
                import requests
                url = self.config.get("ollama_url", "http://localhost:11434")
                model = self.config.get("local_model", "qwen2.5:7b")
                requests.post(url + "/api/generate", json={"model": model, "prompt": "", "stream": False}, timeout=30)
                self._log("Ollama warmup done")
            except Exception as e:
                self._log("Ollama warmup skip: %s" % str(e)[:40])
            try:
                self._load_lazy("vector_store")
                self._log("Vector store warmup done")
            except Exception as e:
                self._log("Vector warmup skip: %s" % str(e)[:40])
        except Exception:
            pass

    def install_crash_hook(self):
        """把未捕获异常写进 data/logs/crashes.log（由程序入口显式调用）

        只在真跑程序时装 —— 见 __init__ 里的说明，
        别让测试/工具把自己的崩溃写进用户的日志。
        """
        sys.excepthook = self._global_excepthook
        self._owns_excepthook = True
        return True

    def _global_excepthook(self, exc_type, exc_value, exc_tb):
        try:
            with open(self.crash_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now()}] 崩溃: {exc_type.__name__}: {exc_value}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n")
        except Exception as e:
            self._log("异常: " + str(e)[:80])
        sys.__excepthook__(exc_type, exc_value, exc_tb)

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
        except Exception:
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

    def _start_background(self):
        """P2-4: 延迟3秒启动后台服务，不阻塞UI"""
        time.sleep(3)
        # 定时任务（内部会启动连续学习线程）
        try:
            self.call("scheduler", "start")
            self._log("定时任务已启动")
        except Exception as e:
            self._log("定时任务启动失败: %s" % str(e)[:60])
        # 热更新检测（每5分钟自动扫 .py 变化）
        try:
            hr = self._load_lazy("hot_reload")
            if hr and hasattr(hr, "auto_reload"):
                hr.auto_reload()
                self._log("热更新已启动")
        except Exception as e:
            self._log("热更新启动失败: %s" % str(e)[:60])
        # 模块服务器（本机插件仓库，127.0.0.1:8899）
        # 配置成远程地址时只连远程、不拉起本地服务（见 部署步骤.md 第五节）
        try:
            cfg_url = str(self.config.get("module_server", "") or "")
            if (not cfg_url) or ("127.0.0.1" in cfg_url) or ("localhost" in cfg_url):
                from core.module_server import ModuleServer
                if getattr(self, "_module_server", None) is None:
                    self._module_server = ModuleServer(self)
                    self._log(str(self._module_server.start())[:70])
            else:
                self._log("模块服务器: 配置为远程地址 %s，不拉起本地服务" % cfg_url[:40])
        except Exception as e:
            self._log("模块服务器启动失败: %s" % str(e)[:60])
        # 手机远程（局域网访问，失败不影响主程序）
        try:
            mr = self._load_lazy("mobile_remote")
            if mr and hasattr(mr, "start"):
                self._log(str(mr.start())[:40])
        except Exception as e:
            self._log("移动端启动失败: %s" % str(e)[:60])
        # MCP 服务端 + 客户端
        # 服务端是内嵌的本地工具服务：把 chat / search / run_code / backup
        # 包成 HTTP 接口（127.0.0.1:3742），供客户端那条「本地工具」配置连。
        # 原来这里只调了 ms.run()（返回工具清单，什么也不启动），
        # start_http() 全项目没有调用点，所以那个服务从来没起来过。
        try:
            ms = self._load_lazy("mcp_server")
            if ms and hasattr(ms, "start_http"):
                self._log("本地工具服务: %s" % str(ms.start_http())[:80])
        except Exception as e:
            self._log("本地工具服务启动失败: %s" % str(e)[:60])
        try:
            mc = self._load_lazy("mcp_client")
            if mc:
                r = mc.run()
                self._log("MCP客户端: %d个工具" % r.get("可用工具数", r.get("工具数", 0)))
        except Exception as e:
            self._log("MCP客户端: %s" % str(e)[:40])
        # Ollama 后台预热
        threading.Thread(target=self._warmup_ollama, daemon=True).start()
        # 定期内存清理：memory_optimizer 登记了很久没人调用
        # （它只做 gc.collect() + 收窄内部历史缓存，不动任何数据，放后台安全）
        try:
            self.call("memory_optimizer", "__no__")
            mo = self.modules.get("memory_optimizer")
            if mo is not None and hasattr(mo, "start_periodic"):
                r = mo.start_periodic(1800)
                self._log("内存优化: %s" % str(r.get("状态", "已启动")))
        except Exception as e:
            self._log("内存优化启动失败: %s" % str(e)[:60])

    # 启动备份的节流间隔（小时）：距上次备份不到这么久就跳过，
    # 免得一天重启十次就备十份。
    _AUTO_BACKUP_MIN_GAP_H = 6

    # 聊天活跃窗口（秒）：一轮回复结束后，后台闭环还要让路多久。
    # 放 60 秒太长（聊得越久、记忆沉淀和反思越滞后），放太短又会跟下一句话抢模型。
    # 25 秒是折中。改这里即可，reply_pipeline / legacy_reply 都读这个值。
    _CHAT_ACTIVE_SEC = 25

    def _auto_backup(self):
        """启动时自动备份一次 —— 走真正的备份系统（core/backup.py）

        和历史的关系
        ------------
        原来这里是自己拷几个关键文件到 data/backup_MMDD_HHMM、留最近 2 份。
        但项目里本来就有 core/backup.py：增量、排除 datasets/cache/logs、
        写 backups/、还支持加密导出和恢复。两套并存的问题不只是重复：
          · 产物分散在两个地方（data/backup_* 和 backups/backup_*），
            要恢复时不知道该看哪个
          · 自检的"📦 备份"数的是旧的 data/backup_*，真正的 backups/ 反而没数
          · 旧那套的排除规则是手写的文件清单，容易和实际存储漂移
            （历史上就漏备过 memory.json / graph.json / chats.db）
        现在融合成一条：启动时触发真正的备份，产物统一进 backups/。

        另加节流：距上次备份不足 _AUTO_BACKUP_MIN_GAP_H 小时就跳过。
        """
        try:
            from core.backup import Backup
            bk = Backup(self)
            last = bk._last_backup_path()
            if last and self._backup_is_recent(last):
                return
            r = bk.backup_now() or {}
            if r.get("成功"):
                self._log("启动备份完成: %s（%s）"
                          % (r.get("备份到"), "增量" if r.get("增量") else "全量"))
            else:
                self._log("启动备份未完成: %s" % str(r.get("错误"))[:60])
        except Exception as e:
            self._log("启动备份失败: %s" % str(e)[:60])

    def _backup_is_recent(self, path):
        """最近的备份是否还在节流窗口内"""
        import time as _t
        try:
            age_h = (_t.time() - os.path.getmtime(path)) / 3600.0
            return age_h < self._AUTO_BACKUP_MIN_GAP_H
        except Exception:
            return False

    def _warmup_ollama(self):
        from core.self_check import warmup_ollama
        return warmup_ollama(self)

    def _check_ollama(self):
        from core.self_check import check_ollama
        return check_ollama(self)

    def _check_cloud(self):
        from core.self_check import check_cloud
        return check_cloud(self)

    def _health_score(self):
        from core.self_check import health_score
        return health_score(self)

    def _deep_check(self):
        from core.self_check import deep_check
        return deep_check(self)

    def _auto_unload_loop(self):
        import time as _t, gc
        # 常驻白名单：核心 + 后台服务（定时任务/热更新/手机远程/学习闭环等带独立线程的模块不可卸载，
        # 否则 stop() 会停掉服务线程——热更新失效、手机远程断连的根因）
        core = {"llm", "vector_store", "auth", "backup", "knowledge_graph",
                "rules_engine",
                "scheduler", "hot_reload", "mobile_remote", "error_lib",
                "learning_loop", "memory_loop"}
        while True:
            _t.sleep(30)
            try:
                now = _t.time()
                to_unload = []
                for name in list(self.modules.keys()):
                    if name in core:
                        continue
                    last = self._last_use.get(name, 0)
                    if last and now - last > 300:  # P0-1: 5分钟才卸载，避免反复懒加载拖慢
                        to_unload.append(name)
                for name in to_unload:
                    try:
                        mod = self.modules.get(name)
                        for m in ["stop", "close", "shutdown", "cleanup"]:
                            fn = getattr(mod, m, None)
                            if fn:
                                try:
                                    fn()
                                except Exception as e:
                                    self._log("异常: " + str(e)[:80])
                        del self.modules[name]
                        if name in self._lazy:
                            mod_path = "core." + self._lazy[name][0]
                            if mod_path in sys.modules:
                                try:
                                    del sys.modules[mod_path]
                                except Exception as e:
                                    self._log("异常: " + str(e)[:80])
                        gc.collect()
                        self._log("真卸载模块: %s" % name)
                    except Exception as e:
                        self._log("卸载%s失败: %s" % (name, str(e)[:50]))
            except Exception as e:
                self._log("自动卸载线程出错: %s" % str(e)[:50])

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
                        except Exception:
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
                    setattr(instance, "llm", self.modules["llm"])
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
            setattr(mod, "llm", llm)
            setattr(mod, "_model", llm)
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

    def _set_status(self, text):
        """更新 UI 状态栏"""
        if hasattr(self, 'status_cb') and self.status_cb:
            try: self.status_cb(text)
            except: pass

    def _warn_user(self, text, detail=None):
        """用户能看见的告警：状态栏一行 + 日志一行。

        后处理（记忆沉淀 / 技能捕获 / 后台整理）出错原来只进日志，界面上完全无感，
        用户只会觉得"它怎么好像没记住"。这类"坏了但不报错"的降级要留个痕迹。
        """
        try:
            self._set_status("⚠ " + text)
        except Exception:
            pass
        self._log(text + ((": " + str(detail)[:80]) if detail else ""), "WARN")

    def _log(self, msg: str, level: str = "INFO") -> None:
        line = "[%s][%s] %s" % (datetime.now().strftime("%H:%M:%S"), level, msg)
        if level in ("WARN", "ERROR"):
            print(line)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _warn(self, msg): self._log(msg, "WARN")
    def _error(self, msg): self._log(msg, "ERROR")
    def _debug(self, msg): self._log(msg, "DEBUG")

    def _load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                return json.load(open(self.config_path, "r", encoding="utf-8"))
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        # 首次运行：以脱敏模板 config.default.json 为底生成一份可用的 config.json。
        # 发布包只带模板（不含任何密钥），开发机上那份带密钥的 data/config.json 不打包。
        for tpl in (os.path.join(self.base, "config.default.json"),
                    os.path.join(self.res_base, "config.default.json"),
                    os.path.join(self.res_base, "data", "config.default.json")):
            try:
                if not os.path.exists(tpl):
                    continue
                d = json.load(open(tpl, "r", encoding="utf-8"))
                if isinstance(d, dict) and d:
                    with open(self.config_path, "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False, indent=2)
                    self._log("已从模板 config.default.json 生成首次配置")
                    return d
            except Exception as e:
                self._log("读取配置模板失败: " + str(e)[:60])
        return {"model_mode": "本地路由", "local_model": "xiao6-7b:latest",
                "small_model": "xiao6-7b:latest",
                "cloud_model": "qwen-turbo"}

    def save_config(self) -> None:
        """原子写 + 读回校验：先写临时文件再替换；写后立即读回验证；失败保留旧配置"""
        import os as _os
        tmp = self.config_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            # 读回校验
            with open(tmp, encoding="utf-8") as f:
                _back = json.load(f)
            if not isinstance(_back, dict):
                raise ValueError("配置校验失败：不是字典")
            _os.replace(tmp, self.config_path)  # 原子替换
            self._log("配置已保存并校验通过")
            return True
        except Exception as e:
            self._log("配置校验失败，保留旧配置: " + str(e)[:60])
            try:
                if _os.path.exists(tmp):
                    _os.remove(tmp)
            except Exception:
                pass
            return False

    def _load_memory(self):
        """修复：无文件时返回空字典，兼容旧列表格式"""
        if os.path.exists(self.memory_path):
            try:
                d = json.load(open(self.memory_path, "r", encoding="utf-8"))
                if isinstance(d, dict):
                    return d
                if isinstance(d, list):
                    return {"default": d}
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        return {}

    def save_memory(self):
        """MED-01: 原子写 + 加锁，防止多线程写坏文件"""
        import threading
        if not hasattr(self, "_mem_lock"):
            self._mem_lock = threading.Lock()
        with self._mem_lock:
            _tmp = self.memory_path + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as f:
                json.dump(self.memory, f, ensure_ascii=False)
            os.replace(_tmp, self.memory_path)

    def _load_kb(self):
        if os.path.exists(self.kb_index):
            try:
                return json.load(open(self.kb_index, "r", encoding="utf-8"))
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        return []

    def save_kb(self):
        """原子写"""
        _tmp = self.kb_index + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            json.dump(self.kb_items, f, ensure_ascii=False, indent=2)
        os.replace(_tmp, self.kb_index)

    def confirm(self, action, detail):
        """危险操作确认：GUI 可注册 confirm_cb（弹窗），无则放行"""
        cb = getattr(self, "confirm_cb", None)
        if cb:
            try:
                return bool(cb(action, detail))
            except Exception:
                pass
        return True

    def kb_add(self, title, content, category="默认"):
        self.kb_items.append({"title": title, "content": content, "category": category, "time": time.time()})
        self.save_kb()

    def kb_search(self, query, category=None):
        results = []
        for item in self.kb_items:
            if category and item.get("category") != category:
                continue
            if query in item.get("title", "") or query in item.get("content", ""):
                results.append(item)
        return results

    def kb_categories(self):
        cats = set()
        for item in self.kb_items:
            cats.add(item.get("category", "默认"))
        return list(cats)

    def rule(self, key, default=None):
        """从规则引擎读参数；规则引擎异常时回退 config/默认（不崩）"""
        try:
            re_ = self.modules.get("rules_engine")
            if re_ is not None:
                return re_.get(key, default)
        except Exception:
            pass
        return default

    def _compress_old(self, items):
        """D6: 把最旧的若干条对话压缩成一条摘要记忆（规则式，不调 LLM）"""
        try:
            users = [str(it.get("u", ""))[:80] for it in items if it.get("u")]
            key = "；".join([u for u in users if u and u != "[压缩记忆]"][-5:])
            if not key:
                return None
            return {"u": "[压缩记忆]", "a": "此前聊过: " + key,
                    "t": time.time(), "compressed": True}
        except Exception:
            return None

    def mem_add(self, user, assistant):
        # v11: 多用户隔离——按用户存记忆
        # v15: 记忆去重——和上一条用户输入完全一样就不重复存
        uname = getattr(self, 'current_user', None) or 'default'
        mem_list = self.memory.setdefault(uname, [])
        # 检查重复：上一条的用户输入和当前一样就跳过
        if mem_list and mem_list[-1].get("u") == user:
            # 只更新助手回复，不新增一条
            mem_list[-1]["a"] = assistant
            mem_list[-1]["t"] = time.time()
            self.save_memory()
            return
        mem_list.append({"u": user, "a": assistant, "t": time.time()})
        cap = self.rule("记忆.每人上限", 200)
        if len(mem_list) > cap:
            # D6: 丢弃前先把最旧 10 条压缩成 1 条摘要，长程记忆不蒸发
            comp = self._compress_old(mem_list[:10])
            if comp:
                mem_list = [comp] + mem_list[10:]
            self.memory[uname] = mem_list[-cap:]
        self.save_memory()
        return

    def mem_recent(self, n=5):
        uname = getattr(self, 'current_user', None) or 'default'
        mem = self.memory.get(uname, [])
        return mem[-n:] if mem else []

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
            self._log("调用失败: %s 没有 %s 方法" % (name, method), "WARN")
            return {"ok": False,
                    "error": "「%s」没有「%s」这个功能（功能不可用，版本可能不一致）"
                             % (self._disp(name), method)}
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self._log("错误: %s.%s - %s" % (name, method, str(e)[:50]))
            return {"ok": False,
                    "error": "「%s」的「%s」出错了：%s" % (self._disp(name), method, str(e)[:80])}

    def get_stats(self):
        return self.stats

    def snapshot(self):
        return {"modules": list(self.modules.keys()), "lazy": list(self._lazy.keys())}

    # publish / subscribe 事件总线已删除（2026-10-11）。
    # 原因：subscribe() 从初始提交起零调用，publish("perceive") 每条用户消息白跑一次；
    # 而它唯一想做的事（通知后台"用户在聊天"）实际由 _chat_active_until 轮询完成，
    # 后处理则改用 _idle_queue 排队。留着一个没人接的总线只会误导后来的人。
    # 真要重启推送式通知，先补 unsubscribe —— 否则 _auto_unload_loop 真卸载模块后，
    # 回调会留在订阅表里打到已卸载对象上。

    def _chat_busy(self):
        """聊天中（含排队）或回复后120s内返回 True，后台闭环应让路，避免抢 Ollama"""
        if getattr(self, "_chat_in_progress", False):
            return True
        return time.time() < getattr(self, "_chat_active_until", 0)

    def reply(self, user_input, on_token=None):
        try:
            # P0-01: /model 热切换指令拦截
            t = user_input.strip()
            if t.startswith("/model "):
                name = t[7:].strip()
                llm = self.modules.get("llm")
                if llm and hasattr(llm, "switch_model"):
                    r = llm.switch_model(name)
                    if r.get("ok"):
                        return "✅ 已切换到模型: " + name
                    return "❌ 切换失败: " + str(r.get("msg", ""))

            self._chat_in_progress = True  # 聊天中（含排队期）：后台闭环持续让路
            self._chat_active_until = time.time() + self._CHAT_ACTIVE_SEC
            return self._reply_inner(user_input, on_token=on_token)
        except Exception as e:
            # 错误入库（可在「设置 → 系统」里查看/清空）+ 日志，聊天只给友好提示
            self._log("回复异常: " + str(e)[:200])
            try:
                self.call("error_lib", "log", "reply", "reply", str(e))
            except Exception:
                pass
            return "（抱歉，回复时出了点问题，详情已记入日志）"
        finally:
            # P0-1: 无论成功失败都复位，防止后台闭环永久让路
            self._chat_in_progress = False
            self._chat_active_until = time.time() + self._CHAT_ACTIVE_SEC


    def _bg_loop(self):
        """P0-4: 后台任务单线程工作循环"""
        while True:
            try:
                task = self._bg_queue.get()
                if task is None:
                    break
                user_input, answer = task
                self._bg(user_input, answer)
            except Exception as e:
                self._log("后台任务异常: %s" % str(e)[:80])
            finally:
                self._bg_queue.task_done()

    def _defer_to_idle(self, fn):
        """把「要调模型」的后处理排到用户空闲之后再做。

        为什么必须排队、不能当场判断：后处理就在回复刚结束那一刻执行，
        那一刻用户必然刚说过话 —— 任何「现在空闲吗」的检查都必然为否。
        原来的 _idle 就是这么恒假了三个星期的，所以这里换成排队等空闲。
        """
        try:
            if self._idle_queue.qsize() > 200:
                self._warn_user("后台整理任务积压过多，跳过一轮")
                return
            self._idle_queue.put(fn)
        except Exception:
            pass

    def _idle_worker(self):
        """空闲任务线程：等不忙了再做反思 / 记忆闭环"""
        while True:
            try:
                task = self._idle_queue.get()
                if task is None:
                    break
                # 最多等 10 分钟；等不到就放弃这一轮，避免无限积压
                deadline = time.time() + 600
                while self._chat_busy() and time.time() < deadline:
                    time.sleep(5)
                if self._chat_busy():
                    # 一直没等到空闲：这轮反思/记忆沉淀就没了，得让用户知道
                    self._warn_user("你聊得太连续，后台整理这轮跳过了")
                    continue
                try:
                    task()
                except Exception as e:
                    self._warn_user("后台整理出错（详情见日志）", e)
                time.sleep(1)          # 任务之间喘口气，别一口气把模型打满
            except Exception as e:
                self._log("空闲任务线程异常: %s" % str(e)[:80])

    def set_private_mode(self, on):
        """P1-21: 开启/关闭隐私模式（无痕会话）"""
        self._private_mode = bool(on)
        self._log("隐私模式: " + ("开启" if on else "关闭"))

    def _bg(self, user_input, answer):
        # P1-21: 隐私模式（无痕会话）不写记忆/向量/日志
        if getattr(self, "_private_mode", False):
            self._log("隐私模式：本次对话不记录")
            return
        try:
            # 存向量
            vs = self.modules.get("vector_store")
            if vs:
                vs.add(user_input, answer)
            # 存知识图谱
            kg = self.modules.get("knowledge_graph")
            if kg:
                kg.add_dialog(user_input, answer)
            # P2-8: 每次回答后轻量自评估（规则打分，不占模型，沉淀到 data/self_eval.json）
            try:
                _rfl = self.modules.get("self_reflect") or self._load_lazy("self_reflect")
                if _rfl and hasattr(_rfl, "quick_eval"):
                    _rfl.quick_eval(user_input, answer)
            except Exception:
                pass
            # 反思（降频：每5轮一次）。要调模型，排到用户空闲后做。
            #
            # 这里原来是 `if _idle and ...`，而 _idle 恒为 False：
            # _chat_active_until 在任务入队前一行刚被设成 now+120，而后处理又恰好
            # 在回复刚结束那一刻执行 —— "现在空闲吗"必然为否。反思/记忆闭环/技能捕获
            # 三条链因此静默失效了三个星期（reflections.json 停在 09-23，
            # episodic_memory.json 也停在 09-23）。结论：换采样点没用，只能排队等空闲。
            if getattr(self, "_reply_n", 0) % 5 == 1:
                self._defer_to_idle(
                    lambda ui=user_input, an=answer:
                        self.call("self_reflect", "reflect", ui, an))
            # 拟人：感知用户情绪 + 记住值得以后提的事
            pers = self.modules.get("personality")
            if pers:
                try:
                    pers.sense_feeling(user_input)
                    pers.remember_event(user_input)
                except Exception:
                    pass
            # 记忆卡：由memory_loop内部统一调用，避免重复触发
            # （之前这里单独调一次，ml.run内部又调一次，导致同一轮写2张卡）
            # ===== 闭环自动接线 =====
            # 记忆闭环：对话→记忆卡→遗忘曲线→到期复习→检索增强。
            # 内部会调模型（memory_cards.maybe_summarize），排到空闲后做。
            def _memory_chain(ui=user_input, an=answer):
                try:
                    ml = self._load_lazy("memory_loop")
                    if ml and hasattr(ml, "run"):
                        # C2: 情景记忆直接接线（不依赖记忆闭环内部流程，禁了闭环也不断线）
                        try:
                            if hasattr(ml, "remember_scene"):
                                ml.remember_scene(ui, an)
                        except Exception:
                            pass
                        ml.run(ui, an)
                except Exception as e:
                    self._warn_user("记忆沉淀失败（详情见日志）", e)
            self._defer_to_idle(_memory_chain)
            # 技能捕获：任务类对话且产出成功 → 存成 SKILL.md。
            # 两点要注意：
            #   1) capture() 是 skill_capture 的方法，skill_distill 只有 distill()。
            #      原来加载错了模块，又用 hasattr 挡着，于是静默失效了很久
            #      （data/skills/ 最后写入停在 09-22）。
            #   2) 它纯写文件、不调模型，所以不必等空闲，立即执行。
            try:
                kw = ["帮我写", "帮我做", "帮我实现", "写一个", "做一个", "实现一个", "修复", "整理一下"]
                if any(k in user_input for k in kw) and not str(answer).startswith(("（", "抱歉", "出错了")):
                    sc = self._load_lazy("skill_capture")
                    if sc:
                        # confirm=True 直接进正式库：confirm_skill() 全项目没有调用方，
                        # 走 pending 的话技能会永远堆在 data/skills_pending/ 没人确认。
                        sc.capture(user_input, str(answer)[:300], success=True, confirm=True)
            except Exception as e:
                # 故意不用 hasattr 兜底：方法名再改错要能在日志里看见，而不是又静默失踪。
                # 同时给用户一行状态栏提示 —— 技能没沉淀下来是用户能感知的损失。
                self._warn_user("技能捕获失败（详情见日志）", e)
            # 任务闭环：智能路由判断复杂任务（关键词→LLM→缓存），自动拆解执行
            try:
                txt = str(user_input)
                verbs = ["做", "写", "实现", "开发", "设计", "搭建", "整理", "制作", "创建", "生成"]
                if len(txt) >= 8 and any(v in txt for v in verbs):
                    sr = self._load_lazy("smart_router")
                    if sr and hasattr(sr, "route"):
                        r = sr.route(txt)
                        if isinstance(r, dict) and r.get("意图") == "task":
                            tl = self._load_lazy("task_loop")
                            if tl and hasattr(tl, "run"):
                                tr = tl.run(txt[:150])
                                self._log("任务闭环(智能路由): %s" % str(tr.get("ok", tr))[:60])
            except Exception:
                pass
        except Exception as e:
            self._log("异常: " + str(e)[:80])

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
                    "rules_engine", "scheduler", "hot_reload", "mobile_remote",
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


    def shutdown(self):
        """优雅退出：保存配置、flush数据、停线程"""
        try:
            self._log("正在退出...")
            # 1. 保存配置
            try:
                self.save_config()
                self._log("配置已保存")
            except Exception as e:
                self._log("保存配置失败: %s" % str(e)[:60])
            
            # 2. 保存向量库
            try:
                vs = self.modules.get("vector_store")
                if vs and hasattr(vs, 'save'):
                    vs.save()
                    self._log("向量库已保存")
            except Exception as e:
                self._log("保存向量库失败: %s" % str(e)[:60])
            
            # 3. 保存记忆
            try:
                self.save_memory()
                self._log("记忆已保存")
            except Exception as e:
                self._log("保存记忆失败: %s" % str(e)[:60])

            # 4. 收掉 MCP 的 stdio 子进程 和 内嵌的本地工具服务
            #    npx / node 那些是用命令行起的，不收就会变成孤儿进程挂在后台。
            try:
                mc = self.modules.get("mcp_client")
                if mc and hasattr(mc, "stop"):
                    r = mc.stop()
                    self._log("MCP 子进程已收: %s" % (r or ""))
            except Exception as e:
                self._log("收 MCP 子进程失败: %s" % str(e)[:60])
            try:
                ms = self.modules.get("mcp_server")
                if ms and hasattr(ms, "stop_http"):
                    ms.stop_http()
                    self._log("本地工具服务已停")
            except Exception as e:
                self._log("停本地工具服务失败: %s" % str(e)[:60])

            self._log("退出完成")
        except Exception as e:
            print("shutdown error:", e)

    # pipeline 降级策略：出错不是"永久放弃"，而是进入冷却，到点自动重试。
    #
    # 原来的写法是一抛异常就 self._use_pipeline = False 并且永不恢复，后果是
    # 一次网络抖动 / 模型临时抽风，程序就静默地一直走旧流程直到重启 —— 功能还在，
    # 但路径换了，而且日志里只有一行，很难发现。
    # 现在改成指数退避：失败后冷却 60s 再试，连续失败翻倍，最长 30 分钟；
    # 一旦重试成功就完全恢复并清零计数。
    # 冷却时间做成类属性，测试里可以直接改小以便验证恢复路径。
    _PIPELINE_COOLDOWN_BASE = 60      # 首次失败后的冷却秒数
    _PIPELINE_COOLDOWN_MAX = 1800     # 冷却上限（30 分钟）

    def _pipeline_ready(self):
        """现在能不能走 pipeline：要么正常可用，要么冷却期已过可以再试一次"""
        if self._pipeline is None:
            return False
        if self._use_pipeline:
            return True
        return time.time() >= getattr(self, "_pipeline_retry_at", 0.0)

    def _pipeline_failed(self, err):
        """pipeline 出错：累计计数、按指数退避设置冷却、记错误库"""
        n = getattr(self, "_pipeline_fail_count", 0) + 1
        self._pipeline_fail_count = n
        cd = min(self._PIPELINE_COOLDOWN_BASE * (2 ** (n - 1)), self._PIPELINE_COOLDOWN_MAX)
        self._use_pipeline = False
        self._pipeline_retry_at = time.time() + cd
        self._legacy_fallback_count = getattr(self, "_legacy_fallback_count", 0) + 1
        self._log("Pipeline异常(连续第%d次，累计%d次)，降级走旧流程，%d 秒后重试: %s"
                  % (n, self._legacy_fallback_count, cd, str(err)[:110]))
        try:
            self.call("error_lib", "log", "pipeline", "reply", str(err))
        except Exception:
            pass

    # 这些是"其实没答出来"的占位串，用来判断要不要走端侧兜底
    # 「功能不可用」是 trunk.call 失败时的稳定标记（见 call()），
    # 改了那边的文案记得同步这里。
    _FAIL_MARKS = ("（抱歉", "回复时出了点问题", "功能不可用",
                   "Pipeline 不可用", "服务不可用")

    def _looks_failed(self, answer):
        """判断这次回复其实是失败的（空串 / 明显的错误占位）"""
        try:
            a = "" if answer is None else str(answer).strip()
        except Exception:
            return True
        if not a:
            return True
        if len(a) > 60:          # 正常回答不会这么短就带失败特征
            return False
        return any(m in a for m in self._FAIL_MARKS)

    def _local_fallback_reply(self, user_input):
        """本地模型不可用时的端侧兜底

        local_fallback 这个模块登记了很久、全项目没人调用它。
        它做的就是这件事：Ollama 没起来时，至少回一句人话
        （"启动 Ollama 就能正常聊"），而不是让用户对着空气发呆。
        """
        try:
            if "local_fallback" not in self.modules:
                self.call("local_fallback", "__no__")
            fb = self.modules.get("local_fallback")
            if fb is not None and hasattr(fb, "reply"):
                t = fb.reply(user_input)
                if t:
                    self._log("模型不可用，已用端侧兜底回复")
                    return t
        except Exception as e:
            self._log("端侧兜底失败: %s" % str(e)[:60])
        return None

    def _reply_inner(self, user_input, on_token=None):
        """回复主流程 v2：优先 pipeline，出错先降级、冷却后自动重试"""
        answer = None
        if self._pipeline_ready():
            was_degraded = not self._use_pipeline
            try:
                answer = self._pipeline.run(user_input, on_token=on_token)
            except Exception as e:
                self._pipeline_failed(e)
            else:
                if was_degraded:
                    self._log("Pipeline 已恢复（此前连续失败 %d 次）"
                              % getattr(self, "_pipeline_fail_count", 0))
                # 成功即完全恢复，退避计数清零
                self._use_pipeline = True
                self._pipeline_fail_count = 0
                self._pipeline_retry_at = 0.0
        if answer is None:
            # 回退到旧流程
            # 回退到旧流程（实现在 core/pipeline/legacy_reply.py）
            from core.pipeline.legacy_reply import run as _legacy_reply
            answer = _legacy_reply(self, user_input, on_token=on_token)
        # 全都失败（空回复 / 错误占位）→ 端侧兜底给一句人话
        if self._looks_failed(answer):
            fb = self._local_fallback_reply(user_input)
            if fb:
                return fb
        return answer
