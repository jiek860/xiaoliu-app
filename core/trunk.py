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
        """后台预热Ollama"""
        try:
            import requests
            url = self.config.get("ollama_url", "http://localhost:11434")
            requests.get(url + "/api/tags", timeout=2)
            self._log("Ollama预热完成")
        except Exception:
            pass

    def _check_ollama(self):
        try:
            import requests
            url = self.config.get("ollama_url", "http://localhost:11434")
            r = requests.get(url + "/api/tags", timeout=3)
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "models": models}
        except Exception as e:
            return {"ok": False, "error": str(e)[:50]}

    def _check_cloud(self):
        try:
            import requests
            url = self.config.get("cloud_url", "")
            key = self.config.get("cloud_key", "")
            if not url or not key:
                return {"ok": False, "error": "未配置"}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:50]}

    def _health_score(self):
        score = 100
        if not self._check_ollama()["ok"]:
            score -= 20
        if not self._check_cloud()["ok"]:
            score -= 10
        return score

    def _deep_check(self):
        """深度自检报告 v2：11 项检查（含目录层级/星型拓扑/结构契约）"""
        import py_compile, re as _re
        import glob as _g          # 提前导入，确保全程可用
        results = []
        errors = []
        def log(m):
            results.append(m)

        log("=== 深度自检报告 v2 ===")
        log("时间: %s" % datetime.now().strftime("%H:%M:%S"))
        _who = ""
        try:
            _r = self.call("auth", "whoami")
            if isinstance(_r, dict):
                _who = str(_r.get("user", ""))
        except Exception:
            pass
        log("账号: %s" % (_who if _who else "未登录(游客)"))
        log("")

        # 1. 语法检查（全程序目录，非仅 core）
        ok = fail = 0
        bad = []
        for root, _, files in os.walk(self.base):
            if any(x in root for x in ("backups", "staging", "dist", ".git", "node_modules")):
                continue
            for f in files:
                if f.endswith(".py") and not f.startswith("_"):
                    try:
                        py_compile.compile(os.path.join(root, f), doraise=True)
                        ok += 1
                    except Exception:
                        fail += 1
                        if len(bad) < 2:
                            bad.append(os.path.relpath(os.path.join(root, f), self.base))
        log("📁 语法: %d通过 %d失败 %s" % (ok, fail, ("❌" + str(bad)) if bad else "✓"))
        if fail:
            errors.append("语法失败%d个: %s" % (fail, bad))

        # 2. 核心模块
        miss = [n for n in ("llm", "vector_store", "knowledge_graph", "auth", "backup")
                if n not in self.modules]
        log("🧩 核心模块: %s" % ("✓ 5个全在" if not miss else "❌缺 " + str(miss)))
        if miss:
            errors.append("核心模块缺失: " + str(miss))

        # 3. 懒加载模块对账（登记表 ↔ 文件 ↔ 类名）
        #    两处必须和 _load_lazy 的真实规则一致，否则全是误报：
        #      a) 登记表直接用内存里的 self._lazy，不要再去正则解析源码 ——
        #         原来那种扫 '": (' 的写法只认得出缩进不整齐的行，90 条里只认出 12 条
        #      b) 文件查找要先 modules/installed，找不到再回退 core/（_load_lazy 就是这么做的）
        try:
            lazy = getattr(self, "_lazy", {}) or {}
            lmiss = []
            for k, v in lazy.items():
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    f, c = v[0], v[1]
                elif isinstance(v, (list, tuple)) and v:
                    f, c = v[0], ""
                else:
                    f, c = str(v), ""
                fp = os.path.join(self.modules_dir, f + ".py")
                if not os.path.exists(fp):
                    fp = os.path.join(self.base, "core", f + ".py")
                if not os.path.exists(fp):
                    lmiss.append(k + "(文件)")
                elif c:
                    try:
                        if not _re.search(r"class\s+" + _re.escape(c) + r"\b",
                                          open(fp, encoding="utf-8").read()):
                            lmiss.append(k + "(类名)")
                    except Exception:
                        pass
            log("🧩 懒加载模块: %d条 %s" % (len(lazy), "✓ 全对齐" if not lmiss else "❌" + str(lmiss[:3])))
            if lmiss:
                errors.append("懒加载对账失败: " + str(lmiss[:3]))
        except Exception as e:
            log("🧩 懒加载模块: ❌ %s" % str(e)[:40])
            errors.append("懒加载对账失败: %s" % str(e)[:40])

        # 4. Ollama
        o = self._check_ollama()
        log("🤖 Ollama: %s" % ("✅ %d个模型" % len(o["models"]) if o["ok"] else "❌ " + o["error"]))
        if not o["ok"]:
            errors.append("Ollama: " + o["error"])

        # 5. 云端
        c = self._check_cloud()
        log("☁️ 云端: %s" % ("✅ 已配置" if c["ok"] else "❌ " + c["error"]))
        if not c["ok"]:
            errors.append("云端: " + c["error"])

        # 6. 错误库状态
        #    这里原来叫「自愈闭环」，检的是 self_heal 模块在不在。
        #    那个模块已删除（名字叫自愈、实际只标记不改代码），
        #    现在只报错误库自己还有多少条未修复。
        try:
            n = 0
            try:
                r = self.call("error_lib", "list")
                n = (r or {}).get("未修复", 0)
            except Exception:
                pass
            log("🩹 错误库: 未修复错误 %d 条%s" % (n, " ⚠" if n else " ✓"))
            if n:
                errors.append("有%d条未修复错误" % n)
        except Exception as e:
            log("🩹 错误库: ❌ %s" % str(e)[:40])

        # 7. 向量/嵌入对齐
        #    向量库已迁到 SQLite + numpy 矩阵：条目在 .data，向量在 ._emb_mat。
        #    原来读的 .embeddings 属性早就不存在了，getattr 默认 {} 恒为 0，
        #    所以不管实际对不对齐都报"差N"—— 纯误报。
        try:
            vs = self.modules.get("vector_store")
            nv = len(getattr(vs, "data", None) or [])
            ne = len(getattr(vs, "embeddings", None) or {})
            if not ne:
                mat = getattr(vs, "_emb_mat", None)
                try:
                    ne = int(mat.shape[0]) if mat is not None else 0
                except Exception:
                    ne = 0
            ok7 = nv == ne
            log("🧮 向量/嵌入: %d/%d %s" % (nv, ne, "✓ 对齐" if ok7 else "❌差%d" % (nv - ne)))
            if not ok7:
                errors.append("向量嵌入不对齐(差%d)" % (nv - ne))
            # P2-8: 自我评估统计
            try:
                _refl = self.modules.get("self_reflect") or self._load_lazy("self_reflect")
                if _refl and hasattr(_refl, "stats"):
                    _st = _refl.stats()
                    _avg = _st.get("平均分")
                    try:
                        _avg_f = float(_avg)
                    except Exception:
                        _avg_f = 0.0
                    log("🏷 自我评估: 平均 %.2f · %d 次" % (
                        _avg_f, _st.get("总反思次数", _st.get("历史数", 0))))
            except Exception:
                pass
        except Exception as e:
            log("🧮 向量/嵌入: ❌ %s" % str(e)[:40])

        # 8. 数据文件完整性
        #    vectors.json / embeddings.json 是旧版遗留，现已迁到 SQLite（vectors.db），
        #    检查它们必然报"损坏"—— 纯误报。SQLite 库用 quick_check 验完整性。
        dmiss = []
        for fn in ("config.json", "graph.json", "memory.json"):
            try:
                json.load(open(os.path.join(self.data_dir, fn), encoding="utf-8"))
            except Exception:
                dmiss.append(fn)
        for fn in ("vectors.db", "chats.db"):
            p = os.path.join(self.data_dir, fn)
            if not os.path.exists(p):
                continue                      # 首次运行还没建，不算错
            try:
                import sqlite3
                con = sqlite3.connect(p)
                con.execute("PRAGMA quick_check").fetchone()
                con.close()
            except Exception:
                dmiss.append(fn + "(损坏)")
        log("🗂 数据文件: %s" % ("✓ 全部可读" if not dmiss else "❌ " + str(dmiss)))
        if dmiss:
            errors.append("数据文件损坏: " + str(dmiss))

        # 9. 崩溃日志（当天新增）
        try:
            n9 = 0
            if os.path.exists(self.crash_path):
                today = datetime.now().strftime("%Y-%m-%d")
                n9 = sum(1 for ln in open(self.crash_path, encoding="utf-8", errors="replace") if today in ln)
            log("📜 崩溃日志: 今天 %d 条 %s" % (n9, "✓" if n9 == 0 else "⚠"))
            if n9:
                errors.append("今天%d条崩溃" % n9)
        except Exception as e:
            log("📜 崩溃日志: ❌ %s" % str(e)[:40])

        # 11. 层级检查（目录层级 / 模块分层 / 星型拓扑 / 方法入口）
        try:
            _lv_err = []
            # 11.1 目录层级
            _need = ["core", "gui", "modules", "modules_repo", "data", "backups", "staging"]
            _miss = [d for d in _need if not os.path.isdir(os.path.join(self.base, d))]
            log("📁 目录层级: %s %s" % ("✓ 7个关键目录齐全" if not _miss else "❌缺", _miss or ""))
            if _miss:
                _lv_err.append("目录缺失: " + str(_miss))
            # 11.2 模块分层注册
            _core_n = len([n for n in ("llm", "vector_store", "knowledge_graph", "auth", "backup", "rules_engine")
                           if n in self.modules])
            _bg_n = len([n for n in ("scheduler", "hot_reload", "mobile_remote") if n in self.modules])
            _lazy_n = len(getattr(self, "_lazy", {}) or {})
            log("🗂 模块分层: 核心%d/6 · 后台%d/3 · 懒加载%d · 当前已加载%d" % (_core_n, _bg_n, _lazy_n, len(self.modules)))
            if _core_n < 6:
                _lv_err.append("核心模块不足(%d/6)" % _core_n)
            # 11.3 星型拓扑：modules 内模块不应互相 import（只准 import core/标准库）
            _viol = []
            _mi = os.path.join(self.base, "modules", "installed")
            if os.path.isdir(_mi):
                _fs = [f for f in os.listdir(_mi) if f.endswith(".py")]
                for _f in _fs:
                    try:
                        _src = open(os.path.join(_mi, _f), encoding="utf-8").read()
                        for _o in _fs:
                            if _o == _f:
                                continue
                            _bn = _o[:-3]
                            if _bn in ("__init__", "config"):
                                continue
                            # 只认"真的导入了这个兄弟模块"：
                            #     from modules.installed.<名> import ...
                            #     import <名> / from <名> import ...
                            # 原来写的是 import\s+.*<名>，只要文件名出现在任意 import 行的
                            # 后半段就报违规，于是 from core.realtime.tts import TTS
                            # 被误判成 realtime_chat.py→tts.py —— 那其实是在导入 core，完全合规。
                            _pat = (r"modules\.installed\." + _re.escape(_bn) + r"\b"
                                    r"|^\s*(?:from|import)\s+" + _re.escape(_bn) + r"\b")
                            if _re.search(_pat, _src, _re.M):
                                _viol.append("%s→%s" % (_f, _o))
                    except Exception:
                        pass
            log("🕸 星型拓扑: %s" % ("✓ 模块间无互相 import" if not _viol else "⚠ " + str(_viol[:4])))
            if _viol:
                _lv_err.append("模块互相import: " + str(_viol[:3]))
            # 11.4 方法入口层级：抽查懒加载前 12 个模块是否有 run/reply
            _mm = []
            _lazy_d = getattr(self, "_lazy", {}) or {}
            for _k, _v in list(_lazy_d.items())[:12]:
                _f = _v[0] if isinstance(_v, (list, tuple)) else str(_v)
                _fp = os.path.join(self.modules_dir, _f + ".py")
                if os.path.exists(_fp):
                    _s2 = open(_fp, encoding="utf-8").read()
                    if "def run" not in _s2 and "def reply" not in _s2:
                        _mm.append(_k)
            log("🔧 方法入口: %s" % ("✓ 抽查12个模块均有 run/reply" if not _mm else "⚠无run: " + str(_mm[:3])))
            if _mm:
                _lv_err.append("模块缺run入口: " + str(_mm[:3]))
            if _lv_err:
                errors.extend(_lv_err)
        except Exception as e:
            log("🗂 层级检查: ❌ %s" % str(e)[:40])

        # 9.5 新增检测项
        try:
            import psutil
            mem=psutil.virtual_memory()
            log("💾 内存: 已用%d%% 可用%dMB"%(mem.percent,mem.available//1048576))
        except Exception: log("💾 内存: psutil未装")
        # 启动耗时：接上 startup_optimizer（它登记了很久没人调用）。
        # 只报数，不做任何"优化动作"——它的 precompile() 会在启动时
        # 编译整个项目，放到这里会把启动拖慢好几秒，不调。
        try:
            import time as _tb
            _el = _tb.time() - getattr(self, "_process_start", _tb.time())
            log("⏱ 启动耗时: %.1f秒（进程起到现在）" % _el)
        except Exception: pass
        try:
            # os.statvfs 是 Unix 专用 API，Windows 上根本没有这个函数，
            # 原来被 except 吞掉，这行从来没打印过。
            import psutil
            _du = psutil.disk_usage(self.base)
            log("💽 磁盘: 可用%dGB / 共%dGB" % (_du.free // 1073741824, _du.total // 1073741824))
        except Exception:
            pass
        try:
            kg = self.modules.get("knowledge_graph")
            if kg:
                n_triples = len(getattr(kg, "data", {}).get("三元组", []))
                log("🧠 知识图谱: %d三元组" % n_triples)
        except Exception:
            pass
        try:
            # 数真正的备份系统（core/backup.py 写 backups/，名字形如 backup_20261010_204104）。
            # 原来数的是 data/backup_* —— 那是已删除的"简单文件拷贝"式备份留下的目录，
            # 真正的 backups/ 反而没被数到。
            import glob
            _b = [d for d in glob.glob(os.path.join(self.base, "backups", "backup_*"))
                  if os.path.isdir(d)]
            _latest = ""
            if _b:
                _latest = "（最近 %s）" % os.path.basename(sorted(_b)[-1])[7:15]
            log("📦 备份: %d个%s" % (len(_b), _latest))
        except Exception: pass
        try:
            mc=self.modules.get("mcp_client")
            if mc:
                r = mc.run() or {}
                # stats() 返回的键是 服务器数 / 工具数，
                # 原来读的是"已连接服务器"/"总服务器" —— 两个都不存在，
                # 于是永远显示 0/0（实际 5 个服务器 37 个工具），
                # 又是那种"键名对不上、又不报错"的静默 bug。
                log("🔌 MCP: %d 个服务器 · %d 个工具" % (
                    r.get("服务器数", 0), r.get("工具数", 0)))
                if r.get("连接失败"):
                    log("   （%d 个服务器连不上）" % len(r["连接失败"]))
            else:
                log("🔌 MCP: 未加载")
        except Exception: pass
        try:
            t0=time.time(); llm=self.modules.get("llm")
            if llm:
                llm.chat("你好"); dt=time.time()-t0
                log("⚡ LLM响应: %.1f秒"%dt)
                if dt>10: errors.append("LLM慢%.1fs"%dt)
        except Exception as e: log("⚡ LLM响应: %s"%str(e)[:40])

        # 9.6 完整体检新增
        try:
            hard=0
            for py in _g.glob(os.path.join(self.base,"core","*.py"))+_g.glob(os.path.join(self.base,"gui","*.py")):
                for line in open(py,encoding="utf-8",errors="ignore"):
                    if self.base.replace("\\", "\\\\") in line and "self.base" not in line: hard+=1
            log("🔗 硬编码路径: %d处 %s"%(hard,"⚠" if hard>10 else "✓"))
            if hard>20: errors.append("硬编码%d处"%hard)
        except Exception: pass
        try:
            cfg=self.config; need=["local_model","ollama_url"]
            miss=[k for k in need if not cfg.get(k)]
            log("⚙️ 配置: %s"%("✓ 关键项齐" if not miss else "❌缺"+str(miss)))
            if miss: errors.append("配置缺"+str(miss))
        except Exception: pass
        try:
            logf=os.path.join(self.base,"data","logs","app.log"); leak=0
            if os.path.exists(logf):
                for line in open(logf,encoding="utf-8",errors="ignore"):
                    if "sk-" in line or "api_key" in line.lower(): leak+=1
            log("🔒 密钥泄漏: %d处 %s"%(leak,"⚠" if leak else "✓"))
        except Exception: pass
        try:
            boot=getattr(self,"_boot_time",None)
            if boot: log("🚀 启动耗时: %.1f秒"%(time.time()-boot))
        except Exception: pass
        try:
            # 聊天记录在 chats.db 的 messages 表（SQLite），
            # 旧的 chat_history.jsonl 早已不用，所以这里一直显示 0 条。
            cf = os.path.join(self.base, "data", "chats.db")
            n = 0
            if os.path.exists(cf):
                import sqlite3
                con = sqlite3.connect(cf)
                try:
                    n = con.execute("select count(*) from messages").fetchone()[0]
                except Exception:
                    n = 0
                con.close()
            log("💬 聊天记录: %d条" % n)
        except Exception: pass
        # 层级检测 + 链接检测
        try:
            loaded=list(self.modules.keys())
            lazy=list(self._lazy.keys())
            never=[m for m in lazy if m not in loaded]
            log("🔗 链接: 已加载%d · 未触发%d"%(len(loaded),len(never)))
            if never: log("   未触发模块: %s"%(", ".join(never[:8])))
        except Exception: pass
        try:
            # 真正的"死模块"检测：模块名在**全项目源码**里除了登记表自己，
            # 一处都没出现过 —— 那就说明没有任何代码路径能用到它。
            #
            # 原来这里只找 trunk.call("名字") 这一种直接引用，而且把"当前没加载"
            # 也算进去，于是按需加载/定时调用的模块全被误报成孤儿
            # （实测报 50 个，其实都是能用的），这行提示因此失去意义。
            # 现在按"名字有没有在别处出现过"判断：出现过就算可达（宁可漏报不误报）。
            import re as _re
            _dirs = ("core", "gui", "modules", "tests", "tools", "scripts")
            _srcs = []
            for _d in _dirs:
                _root = os.path.join(self.base, _d)
                for _r, _ds, _fs in os.walk(_root):
                    _ds[:] = [x for x in _ds if x not in ("__pycache__", "_deprecated")]
                    for _f in _fs:
                        if _f.endswith(".py"):
                            _srcs.append(os.path.join(_r, _f))
            _IGNORE = {os.path.join(self.base, "core", "lazy_config.py")}
            dead = []
            for _name, _tup in self._lazy.items():
                _own = {os.path.join(self.base, "modules", "installed", _tup[0] + ".py"),
                        os.path.join(self.base, "core", _tup[0] + ".py")}
                _pat = _re.compile(r"\b" + _re.escape(_name) + r"\b")
                _hit = False
                for _p in _srcs:
                    if _p in _own or _p in _IGNORE or os.sep + "modules_repo" + os.sep in _p:
                        continue
                    try:
                        if _pat.search(open(_p, encoding="utf-8", errors="ignore").read()):
                            _hit = True
                            break
                    except Exception:
                        continue
                if not _hit:
                    dead.append(_name)
            if dead:
                log("👻 死模块: %d个（登记了但全项目没有调用点）" % len(dead))
                log("   这些模块装了也不会被用到，建议接上入口或从登记表摘掉。")
                log("   %s%s" % (", ".join(dead[:10]), " …" if len(dead) > 10 else ""))
                # 死模块算真问题：它让"模块 N 个"这个数字虚高，
                # 也让插件市场把它们当成可用功能推给用户。
                errors.append("有%d个登记模块没有任何调用点" % len(dead))
            else:
                log("👻 死模块: ✓ 登记的模块都有调用点")
        except Exception:
            pass


                # 10. 健康分（基于以上错误数）
        hs = max(100 - 20 * len(errors), 0)
        log("💯 健康分: %d" % hs)
        log("")
        if errors:
            log("⚠ 发现 %d 类问题：" % len(errors))
            for e in errors:
                log("   · " + e)
        else:
            log("✔ 全部 11 项检查通过")
        report = "\n".join(results)

        # 这里原来会联动 self_heal（自愈闭环：LLM分析→沙盒验证→弹窗确认→应用）。
        # 那个模块已删除 —— 它并不改代码，只是把错误标记成已处理，
        # 却会顺带弹一次确认窗。标记与清理现在由错误库自己做，
        # 定时任务每 4 小时跑一次（见 modules/installed/scheduler.py）。
        return report

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

    def call(self, name: str, method: str, *args, **kwargs) -> any:
        if name in self._aliases:
            name = self._aliases[name]
        if name not in self.modules and name in self._lazy:
            self._load_lazy(name)
        mod = self.modules.get(name)
        if not mod:
            return {"ok": False, "error": "这个功能还没装好，请联系开发者"}
        self._last_use[name] = time.time()
        fn = getattr(mod, method, None)
        if not fn:
            return {"ok": False, "error": "这个功能还没做好，请稍后再试"}
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            self._log("错误: %s.%s - %s" % (name, method, str(e)[:50]))
            return {"ok": False, "error": str(e)[:100]}

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
            self._chat_active_until = time.time() + 120  # P0-2: 聊天活跃窗口(120s)，后台重任务让路
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
            self._chat_active_until = time.time() + 120

    def _reply_legacy(self, user_input, on_token=None):
        self._set_status("💭 正在理解你的问题...")
        # 轮次计数（反思降频用）
        if not hasattr(self, "_reply_n"): self._reply_n = 0
        self._reply_n += 1
        # 磁盘缓存：先查缓存，命中直接返回
        try:
            cache = self._load_lazy('cache')
            if cache:
                cached = cache.get(user_input)
                if cached:
                    self._log('缓存命中: ' + user_input[:30])
                    if on_token: on_token(cached)
                    return cached
        except Exception: pass
        # v12: 电脑控制快速通道——自然语言直接触发本地操作
        try:
            cc = self._load_lazy("computer_controller")
            if cc:
                handled, result = cc.try_handle(user_input)
                if handled:
                    self._log("电脑控制: %s -> %s" % (user_input[:40], str(result)[:60]))
                    # 用LLM把执行结果整理成自然语言
                    llm = self.modules.get("llm")
                    if llm:
                        try:
                            summary = llm.chat([
                                {"role": "system", "content": "你是小6，住在用户电脑里的AI助手。用户要求操作电脑，操作已经执行完毕。请用一句简短的中文告诉用户结果，不要编造结果，不要复述内部细节。"},
                                {"role": "user", "content": "用户说: %s\n执行结果: %s" % (user_input[:120], str(result)[:300])}
                            ])
                            if summary and not summary.startswith("本地模型错误"):
                                result = summary
                        except Exception:
                            pass
                    self.mem_add(user_input, str(result)[:200])
                    return str(result)
        except Exception as e:
            self._log("电脑控制失败: %s" % str(e)[:80])
        # 简单聊天快回：短消息/闲聊跳过向量检索+工具判断，直接调LLM
        _triggers = ("怎么","如何","为什么","写","帮我","代码","python","PyQt","报错","修复","安装","配置","教程","解释","分析","对比","区别","什么是","什么意思","查","搜","最新","今天","新闻","价格","天气","下雨","气温","几度","预报","下载","官网","github","GitHub","文件","读","写","运行","启动","崩溃","错误","异常","优化","性能","设计","方案","计划","写一个","做一个","帮我写")
        _has_complex = any(w in user_input for w in _triggers)
        _is_simple = len(user_input.strip()) <= 15 and not _has_complex

        # 1+1.5+2. 并行检索：向量记忆 + 情景记忆 + 知识图谱（互不依赖，提速）
        context = ""

        def _ctx_v():
            try:
                vs = self.modules.get("vector_store")
                if vs:
                    tk = self.rule("检索.top_k", self.config.get("retrieval_top_k", 3))
                    rs = vs.search(user_input, top_k=tk)
                    return "\n".join([r.get("text", "")[:100] for r in rs]) if rs else ""
            except Exception:
                return ""

        def _ctx_m():
            try:
                ml = self.modules.get("memory_loop")
                if not ml:
                    self._load_lazy("memory_loop")
                    ml = self.modules.get("memory_loop")
                if ml and hasattr(ml, "recall"):
                    out = ""
                    for item in ml.recall(user_input, top_k=2, hours=48):
                        if item.get("type", "") == "情景":
                            out += "\n[%s情景记忆 %s] %s" % (item.get("scene", "?"),
                                                               item.get("time", "?"),
                                                               item.get("text", ""))
                    return out
            except Exception:
                pass
            return ""

        def _ctx_g():
            try:
                kg = self.modules.get("knowledge_graph")
                if kg:
                    r = kg.rag_query(user_input)
                    return ("\n[知识] " + str(r)[:200]) if r else ""
            except Exception:
                pass
            return ""

        if not _is_simple:
            try:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as _ex:
                    for f in (_ex.submit(_ctx_v), _ex.submit(_ctx_m), _ex.submit(_ctx_g)):
                        try:
                            context += f.result(timeout=12)
                        except Exception:
                            pass
            except Exception as e:
                self._log("并行检索失败: " + str(e)[:60])
        # 2.5 联网搜索注入：搜索意图命中 → 深度搜索 → 实时信息进 prompt
        #    （程序替模型完成"抓取"，模型只负责总结——绕开模型对抓取请求的保守拒绝）
        try:
            if self.config.get("联网", True):
                _q = user_input.strip()
                _hits = [w for w in ("查一下","搜一下","搜索","最新","新闻","今天","天气","下雨","气温","几度","预报","价格","多少钱",
                                     "行情","怎么","教程","官网","知乎","B站","b站","GitHub","github",
                                     "百度","下载","是什么","有哪些","推荐","对比","区别","热点","排名")
                         if w in _q]
                if _hits and len(_q) <= 120:
                    ds = self._load_lazy("deep_search")
                    if ds:
                        web = ds.search(_q)
                        if web and str(web).strip():
                            context += "\n[联网] " + str(web)[:800]
                            self._log("联网搜索: " + _q[:40] + " -> " + str(web)[:60].replace("\n"," "))
        except Exception as e:
            self._log("联网搜索失败: " + str(e)[:80])
        # 2.75 工具自动调用：LLM自己判断要不要用工具（不再关键词预筛）
        try:
            if not _is_simple and self.config.get("工具调用", True):
                tc = self._load_lazy("tool_caller")
                if tc:
                    tr = tc.call_tools(user_input)
                    if tr.get("用工具") != "无":
                        context += "\n[工具结果] " + str(tr.get("结果", ""))[:600]
                        self._log("工具自动调用: %s -> %s" % (user_input[:30], str(tr.get("用工具"))[:40]))
        except Exception as e:
            self._log("工具调用失败: " + str(e)[:80])
        # 3. 历史对话（简单聊天少发点，提速）
        if _is_simple:
            hist = self.mem_recent(3)
        else:
            hist = self.mem_recent(15)
        # 历史对话截断（hist已用于messages构建）
        self._set_status("🤖 正在思考...")
        # 4. 调LLM
        llm = self.modules.get("llm")
        if not llm:
            return "LLM未初始化"
        # v13.0: 强人格提示 + few-shot 示例 + 心境驱动
        pers_hint = ""
        few_shot = []
        # 简单问题跳过人格引擎，快回
        if not _is_simple:
            try:
                self._load_lazy("personality")
                pers = self.modules.get("personality")
                if pers:
                    pers_hint = pers.full_hint(user_input)
                    few_shot = pers.few_shot_examples()
            except Exception as e:
                self._log("异常: " + str(e)[:80])
        # 人格提示全部由人格引擎提供（核心宪法+按需分类圣经）
        _custom = self.config.get("ai_persona", "").strip()
        if _custom:
            persona = _custom + ("\n\n" + pers_hint if pers_hint else "")
        else:
            persona = pers_hint if pers_hint else "你是小6，住在用户电脑里的AI朋友。"
        messages = [{"role": "system", "content": persona}]
        if context:
            messages.append({"role": "system", "content": "相关知识: " + context})
        # P1-4: 自我反思教训注入——上次低分反思的真实教训直接影响本次 prompt
        try:
            refl = self.modules.get("self_reflect")
            if not refl:
                self._load_lazy("self_reflect")
                refl = self.modules.get("self_reflect")
            if refl and hasattr(refl, "get_advice"):
                adv = refl.get_advice()
                if adv:
                    messages.append({"role": "system", "content": "自我反思建议: " + adv})
        except Exception:
            pass
        # few-shot：让小模型学说话风格
        for ex in few_shot:
            messages.append({"role": "user", "content": ex["u"]})
            messages.append({"role": "assistant", "content": ex["a"]})
        for h in hist:
            messages.append({"role": "user", "content": h["u"]})
            messages.append({"role": "assistant", "content": h["a"]})
        messages.append({"role": "user", "content": user_input})
        # v12: 流式回复（on_token 提供时逐 token 返回，首字秒出）
        if on_token and hasattr(llm, "stream_chat"):
            answer = llm.stream_chat(messages, on_token=on_token)
            if not answer or str(answer).startswith(("（模型错误", "本地模型错误")):
                answer = llm.chat(messages)
                if on_token and answer:
                    on_token(str(answer))
        else:
            answer = llm.chat(messages)
        # 5. 存记忆
        self.mem_add(user_input, answer)
        # 5.5 群聊（懒加载：装了子智能体就一起答，没装就跳过）
        try:
            gc = self._load_lazy("group_chat")
            if gc and hasattr(gc, "compose"):
                answer = gc.compose(user_input, answer)
        except Exception:
            pass
        # 7.5 编程代码沙盒验证：用户要代码 + 回复含python代码块 → 试跑验证
        try:
            _cw = ["写", "运行", "实现", "代码", "bug", "修复", "脚本", "程序", "函数", "报错"]
            if any(w in user_input for w in _cw) and "```python" in str(answer):
                cr = self._load_lazy("code_runner")
                if cr:
                    import re as _re
                    blocks = _re.findall(r"```python\s*\n(.*?)```", str(answer), _re.S)
                    if blocks:
                        res = cr.run(blocks[0][:2000], timeout=8)
                        _v = "✅ 运行成功" if res.get("成功") else "❌ 运行失败"
                        answer += "\n\n（沙盒验证%s：%s%s）" % (_v, str(res.get("输出", ""))[:120],
                                                           str(res.get("错误", ""))[:80])
                        self._log("代码沙盒验证: %s" % _v)
        except Exception as e:
            self._log("代码验证失败: " + str(e)[:80])
        # 7. 后台处理（记忆/技能/群聊评估等闭环，传最终answer）
        self._bg_queue.put((user_input, answer))  # P0-4: 改单线程队列
        self._chat_in_progress = False
        self._chat_active_until = time.time() + 120  # 回复完成后再给120s让路窗口
        # 把正常LLM答案存进缓存
        try:
            cache = self._load_lazy('cache')
            if cache and answer and len(answer) < 2000:
                cache.set(user_input, answer)
        except Exception: pass
        return answer

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
                self._log("空闲任务积压过多，丢弃一轮后处理")
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
                    self._log("空闲任务：等了10分钟仍在聊天，放弃本轮")
                    continue
                try:
                    task()
                except Exception as e:
                    self._log("空闲任务异常: %s" % str(e)[:80])
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
                    self._log("记忆闭环异常: %s" % str(e)[:80])
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
                # 故意不用 hasattr 兜底：方法名再改错要能在日志里看见，而不是又静默失踪
                self._log("技能捕获失败: %s" % str(e)[:80])
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
    _FAIL_MARKS = ("（抱歉", "回复时出了点问题", "这个功能还没做好",
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
            answer = self._reply_legacy(user_input, on_token=on_token)
        # 全都失败（空回复 / 错误占位）→ 端侧兜底给一句人话
        if self._looks_failed(answer):
            fb = self._local_fallback_reply(user_input)
            if fb:
                return fb
        return answer





























