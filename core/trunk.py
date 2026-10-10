# -*- coding: utf-8 -*-
"""微核躯干 v12.0
核心职责：
1. 模块注册与懒加载（_load_lazy）
2. 回复主流程（reply）：意图识别→检索→工具调用→LLM→闭环
3. 日志与崩溃兜底
4. 配置读取与保存
"""
import os, json, time, threading, sys, traceback, shutil
from datetime import datetime


class Trunk:
    """融合式躯干：核心能力直接内置，扩展模块注册调用"""

    def __init__(self):
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
        sys.excepthook = self._global_excepthook

        self.modules = {}
        self.handlers = {}
        self.events = []
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
        self._aliases = {
            "errors": "error_lib",
            "enhanced_memory": "vector_store",
            "file_reader": "file_upload",
            "web_learner": "proactive_learner",
            "auto_fixer": "error_lib",
            "llm_client": "llm",
            # ---------- 兼容旧 L 模块名 ----------
            "personality": "personality",
            "self_reflect":     "self_reflect",
            "empathy":     "empathy",
            "forgetting_curve":      "forgetting_curve",
            "skill_distill":      "skill_distill",
        }

        self._register_core()
        # P0-4: 后台任务单线程队列，防止连续发消息起多个线程抢资源
        import queue as _q
        self._bg_queue = _q.Queue()
        self._bg_worker = threading.Thread(target=self._bg_loop, daemon=True)
        self._bg_worker.start()
        threading.Thread(target=self._auto_unload_loop, daemon=True).start()
        # 后台服务丢线程，不阻塞 UI 启动
        threading.Thread(target=self._start_background, daemon=True).start()
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
        import json, os
        groups = {"llm":"核心","vector_store":"核心","knowledge_graph":"核心","rules_engine":"核心","auth":"核心","backup":"核心","trunk":"核心","scheduler":"后台","hot_reload":"后台","mobile_remote":"后台","learning_loop":"闭环","self_heal":"闭环","memory_loop":"闭环","task_loop":"闭环","skill_distill":"闭环","smart_router":"智能体","deep_search":"工具","tool_caller":"工具","computer_controller":"工具","code_runner":"工具","file_upload":"工具","multimodal":"工具","voice":"工具","mcp_server":"工具","task_planner":"高级","error_lib":"高级","auto_updater":"高级","proactive_learner":"高级","rag_engine":"高级","reasoning_engine":"高级","plugin_market":"高级","skill_capture":"高级","self_reflect":"L模块","empathy":"L模块","personality":"L模块","forgetting_curve":"L模块","l135_anomaly":"L模块","memory_cards":"L模块"}
        descs = {"llm":"大模型：本地+云端+流式","vector_store":"向量检索：nomic-embed+余弦","knowledge_graph":"知识图谱：三元组+多跳","rules_engine":"规则引擎：底层规则","auth":"账号激活登录：激活码授权","backup":"自动备份：保留2份","trunk":"微核躯干：注册/总线","scheduler":"定时任务：24h后台","hot_reload":"热更新：沙盒+回滚","mobile_remote":"手机远程","learning_loop":"学习闭环：找缺口→搜索→入库","self_heal":"自愈闭环：错误→分析→修复","memory_loop":"记忆闭环：对话→记忆卡→复习","task_loop":"任务闭环：拆步→执行→验证","skill_distill":"技能沉淀：成功任务→SKILL","smart_router":"智能路由：LLM判断谁答","deep_search":"深度搜索：多源并行","tool_caller":"工具调用：LLM自动决定","computer_controller":"电脑控制：鼠标键盘","code_runner":"代码沙盒：隔离跑Python","file_upload":"文件上传：PDF/Word","multimodal":"多模态：看图/听音频","voice":"语音：STT/TTS","mcp_server":"MCP服务：连外部工具","task_planner":"任务规划：自动拆步","error_lib":"错误库：记录+修复建议","auto_updater":"自动更新：自更新流水线","proactive_learner":"主动学习：定时上网找知识","rag_engine":"RAG：检索增强生成","reasoning_engine":"推理引擎：多跳推理","plugin_market":"插件市场：一键装模块","skill_capture":"技能捕获：自动沉淀","self_reflect":"自我反思：回答后打分","empathy":"共情：情绪感知","personality":"人格引擎：小6性格","forgetting_curve":"遗忘：旧记忆自动删","l135_anomaly":"异常检测：行为偏差","memory_cards":"记忆卡：情景记忆"}
        cns = {"trunk":"微核躯干","llm":"大模型","vector_store":"向量检索","knowledge_graph":"知识图谱","rules_engine":"规则引擎","auth":"账号授权","backup":"自动备份","scheduler":"定时任务","hot_reload":"热更新","mobile_remote":"手机远程","learning_loop":"学习闭环","self_heal":"自愈闭环","memory_loop":"记忆闭环","task_loop":"任务闭环","skill_distill":"技能沉淀","smart_router":"智能路由","deep_search":"深度搜索","tool_caller":"工具调用","computer_controller":"电脑控制","code_runner":"代码沙盒","file_upload":"文件上传","multimodal":"多模态","voice":"语音","mcp_server":"MCP服务","task_planner":"任务规划","error_lib":"错误库","auto_updater":"自动更新","proactive_learner":"主动学习","rag_engine":"RAG引擎","reasoning_engine":"推理引擎","plugin_market":"插件市场","skill_capture":"技能捕获","self_reflect":"自我反思","empathy":"共情","personality":"人格引擎","forgetting_curve":"遗忘","l135_anomaly":"异常检测","memory_cards":"记忆卡"}
        all_names = list(self.modules.keys()) + [k for k in self._lazy.keys() if k not in self.modules]
        modules = [{"name":n,"cn":cns.get(n,n),"desc":descs.get(n,""),"group":groups.get(n,"其他"),"loaded":n in self.modules} for n in all_names]
        # 星型：所有模块都连 trunk
        links = [[n, "trunk"] for n in all_names if n != "trunk"]
        # 组内互联
        _groups = {}
        for n in all_names:
            g = groups.get(n, "其他")
            _groups.setdefault(g, []).append(n)
        for g, ms in _groups.items():
            for i in range(len(ms)):
                for j in range(i+1, len(ms)):
                    links.append([ms[i], ms[j]])
        # 关键闭环连接（跨组）
        _loop_links = [["learning_loop","proactive_learner"],["self_heal","error_lib"],
            ["self_heal","auto_updater"],["task_loop","task_planner"],
            
            ["rag_engine","vector_store"],["rag_engine","knowledge_graph"],
            ["rag_engine","deep_search"],["skill_distill","skill_capture"],
            ["memory_loop","memory_cards"],["memory_loop","forgetting_curve"],
            ["self_reflect","personality"],["empathy","personality"],
            ["computer_controller","code_runner"],["file_upload","rag_engine"],
            ["multimodal","llm"],["voice","llm"],["tool_caller","deep_search"]]
        links.extend(_loop_links)
        out = {"modules":modules,"links":links}
        p = os.path.join(self.base, os.path.join("data", "modules_map.js"))
        open(p,"w",encoding="utf-8").write("var MODULE_DATA = " + json.dumps(out, ensure_ascii=False, indent=2) + ";")

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
        try:
            ms = self._load_lazy("mcp_server")
            if ms: ms.run()
        except Exception as e:
            self._log("MCP服务端: %s" % str(e)[:40])
        try:
            mc = self._load_lazy("mcp_client")
            if mc:
                r = mc.run()
                self._log("MCP客户端: %d个工具" % r.get("可用工具数", r.get("工具数", 0)))
        except Exception as e:
            self._log("MCP客户端: %s" % str(e)[:40])
        # Ollama 后台预热
        threading.Thread(target=self._warmup_ollama, daemon=True).start()

    def _auto_backup(self):
        """启动时自动备份 data，留最近2份"""
        import shutil, glob, time
        try:
            data_dir = os.path.join(self.base, "data")
            ts = time.strftime("%m%d_%H%M")
            bak = os.path.join(self.base, "data", "backup_" + ts)
            if os.path.exists(bak): return
            # 只备份关键文件（不备份 vectors.json 太大）
            os.makedirs(bak, exist_ok=True)
            for f in ["config.json", "chat_history.jsonl", "self_eval.json", "crashes.log"]:
                src = os.path.join(data_dir, f)
                if os.path.exists(src):
                    shutil.copy2(src, bak)
            # 只留最近2份
            baks = sorted(glob.glob(os.path.join(self.base, "data", "backup_*")))
            for old_b in baks[:-2]:
                shutil.rmtree(old_b, ignore_errors=True)
            self._log("自动备份完成")
        except Exception as e:
            self._log("备份失败: %s" % str(e)[:40])

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
        """深度自检报告 v2：10 项检查 + 发现问题自动联动自愈闭环"""
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

        # 6. 自修复闭环状态
        try:
            sh_in = "self_heal" in self._lazy or self.has("self_heal")
            n = 0
            try:
                r = self.call("error_lib", "list")
                n = (r or {}).get("未修复", 0)
            except Exception:
                pass
            log("🩹 自愈闭环: 模块%s，未修复错误 %d 条%s" % ("✓" if sh_in else "✗", n, " ⚠" if n else ""))
            if not sh_in:
                errors.append("自愈闭环未注册")
            if n:
                errors.append("有%d条未修复错误" % n)
        except Exception as e:
            log("🩹 自愈闭环: ❌ %s" % str(e)[:40])

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
            import glob
            log("📦 备份: %d个"%len(glob.glob(os.path.join(self.base,"data","backup_*"))))
        except Exception: pass
        try:
            mc=self.modules.get("mcp_client")
            if mc:
                r=mc.run(); log("🔌 MCP: 已连%d/%d"%(r.get("已连接服务器",0),r.get("总服务器",0)))
            else: log("🔌 MCP: 未加载")
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
            # 找孤儿：注册了但 trunk.call 历史里从没出现过的
            # 注意这只是"提示"：事件触发、动态名调用的模块本来就会落到这里，
            # 而且这里不计入 errors / 健康分。别把它显示得像故障。
            import re as _re
            call_hist=set()
            for py in _g.glob(os.path.join(self.base,"core","*.py"))+_g.glob(os.path.join(self.base,"gui","*.py")):
                for line in open(py,encoding="utf-8",errors="ignore"):
                    for m in _re.findall(r'trunk\.call\(["\'](\w+)["\']',line): call_hist.add(m)
                    for m in _re.findall(r'self\.call\(["\'](\w+)["\']',line): call_hist.add(m)
            orphans=[m for m in self._lazy if m not in call_hist and m not in loaded]
            if orphans:
                log("👻 孤儿模块: %d个（提示，不计入健康分）" % len(orphans))
                log("   含义：源码里没有 trunk.call(\"名字\") 直接引用、当前也没加载。")
                log("   事件触发/按需加载的模块本就会出现在这里，属正常现象。")
                log("   %s%s" % (", ".join(orphans[:8]), " …" if len(orphans) > 8 else ""))
            else:
                log("👻 孤儿模块: ✓")
        except Exception: pass


                # 10. 健康分（基于以上错误数）
        hs = max(100 - 20 * len(errors), 0)
        log("💯 健康分: %d" % hs)
        log("")
        if errors:
            log("⚠ 发现 %d 类问题，自动联动自愈闭环…" % len(errors))
            for e in errors:
                log("   · " + e)
        else:
            log("✔ 全部 11 项检查通过")
        report = "\n".join(results)

        # 联动：有问题 → 交给自愈闭环（内部含 LLM分析→沙盒验证→弹窗确认→应用）
        if errors:
            try:
                r = self.call("self_heal", "run")
                report += "\n\n=== 自愈闭环联动 ===\n" + str(r)[:300]
            except Exception as e:
                report += "\n\n=== 自愈闭环触发失败 ===\n" + str(e)[:80]
        return report

    def _auto_unload_loop(self):
        import time as _t, gc
        # 常驻白名单：核心 + 后台服务（定时任务/热更新/手机远程/自愈/学习闭环等带独立线程的模块不可卸载，
        # 否则 stop() 会停掉服务线程——热更新失效、手机远程断连的根因）
        core = {"llm", "vector_store", "auth", "backup", "knowledge_graph",
                "rules_engine",
                "scheduler", "hot_reload", "mobile_remote", "error_lib",
                "learning_loop", "self_heal", "memory_loop"}
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

    def publish(self, event, data=None):
        self.events.append({"event": event, "data": data, "time": time.time()})
        for cb in self.handlers.get(event, []):
            try:
                cb(data)
            except Exception as e:
                self._log("异常: " + str(e)[:80])

    def subscribe(self, event, cb):
        self.handlers.setdefault(event, []).append(cb)

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
            # 错误入库（可被自愈闭环处理）+ 日志，聊天只给友好提示
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
        self.publish("perceive", user_input)
        # 聊天活跃标记（后台学习用它判断是否暂停）＋ 轮次计数（反思降频）
        if not hasattr(self, "last_chat"): self.last_chat = 0.0
        self.last_chat = time.time()
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
            # P0-2: 聊天活跃窗口内（90s）跳过重 LLM 后台任务，不抢模型
            _idle = time.time() >= getattr(self, "_chat_active_until", 0)
            # P2-8: 每次回答后轻量自评估（规则打分，不占模型，沉淀到 data/self_eval.json）
            try:
                _rfl = self.modules.get("self_reflect") or self._load_lazy("self_reflect")
                if _rfl and hasattr(_rfl, "quick_eval"):
                    _rfl.quick_eval(user_input, answer)
            except Exception:
                pass
            # 反思（降频：每5轮一次，省模型排队）
            if _idle and getattr(self, "_reply_n", 0) % 5 == 1:
                self._load_lazy("self_reflect")
                r = self.call("self_reflect", "reflect", user_input, answer)
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
            # 记忆闭环：对话→记忆卡→遗忘曲线→到期复习→检索增强（非活跃窗口才做）
            if _idle:
                try:
                    ml = self._load_lazy("memory_loop")
                    if ml and hasattr(ml, "run"):
                        # C2: 情景记忆直接接线（不依赖记忆闭环内部流程，禁了闭环也不断线）
                        try:
                            if hasattr(ml, "remember_scene"):
                                ml.remember_scene(user_input, answer)
                        except Exception:
                            pass
                        ml.run(user_input, answer)
                except Exception:
                    pass
            # 技能沉淀：任务类对话且产出成功 → 自动捕获技能（非活跃窗口才做）
            if _idle:
                try:
                    kw = ["帮我写", "帮我做", "帮我实现", "写一个", "做一个", "实现一个", "修复", "整理一下"]
                    if any(k in user_input for k in kw) and not str(answer).startswith(("（", "抱歉", "出错了")):
                        sl = self._load_lazy("skill_distill")
                        if sl and hasattr(sl, "capture"):
                            sl.capture(user_input, str(answer)[:300], True)
                except Exception:
                    pass
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
                    "error_lib", "learning_loop", "self_heal", "memory_loop"}
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

    def _reply_inner(self, user_input, on_token=None):
        """回复主流程 v2：优先 pipeline，出错先降级、冷却后自动重试"""
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
                return answer
        # 回退到旧流程
        return self._reply_legacy(user_input, on_token=on_token)





























