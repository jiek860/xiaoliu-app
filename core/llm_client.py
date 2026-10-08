# -*- coding: utf-8 -*-
"""L模块 v8.0 - llm_client
两种模式：
  ① 本地路由：三级智能选模型——简单问候→小模型，日常→主力7b，带图/复杂→视觉VL；
     本地（含回退主力）失败后云端兜底。
  ② 云端模型：只连云端。
群聊子角色可用 force_model 固定模型，不参与路由。"""
import json, os, requests, time, re, threading

# 全局 Ollama 串行锁：主回复/学习闭环/自愈闭环/嵌入等所有本地调用排队依次执行，不并发抢模型
_OLLAMA_LOCK = threading.RLock()


def get_ollama_lock():
    """供其他模块（vector_store 嵌入等）共用同一把锁，实现全程序本地调用串行"""
    return _OLLAMA_LOCK


def _is_cloud_mode(mode):
    m = str(mode).lower()
    return ("云端" in str(mode)) or ("cloud" in m)


class LLMClient:
    def __init__(self, trunk=None):
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = os.path.join(self.base, r"data\config.json")
        self.config = self._load_config()
        self.base_url = self.config.get("ollama_url", "http://localhost:11434")
        self.ollama_down = False
        self._last_call = time.time()
        self._idle_timeout = 7200
        self._unloaded = False
        self._fail_count = 0  # 连续失败计数，3次自动切云端
        # P2-2: 用requests.Session复用连接，提升性能
        import requests as _req
        self._session = _req.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        import threading
        self._timer = threading.Thread(target=self._watchdog, daemon=True)
        self._timer.start()
        # 模型预热：后台线程先加载模型，第一次聊天不等冷加载
        threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self):
        """启动时后台预热模型"""
        try:
            time.sleep(2)
            with get_ollama_lock():
                requests.post(self.base_url + "/api/chat",
                    json={"model": self._main_model(), "messages": [{"role":"user","content":"hi"}],
                          "stream": False, "keep_alive": "2h",
                          "options": {"num_ctx": 4096}},
                    timeout=30)
            if self.trunk: self.trunk._log("模型预热完成")
        except: pass

    # 复杂/看图问题信号：命中则上 qwen3-vl
    HARD_KW = re.compile(
        r"认真|仔细|一步步|逐步|详细分析|深度分析|严谨|推理|推导|证明|算法|数学|"
        r"复杂|多线程|并发|死锁|内存泄漏|架构设计|重构|sql注入|帮我看看这张图|"
        r"这张图|看图|识图|截图里|图片里|图中|图示")

    def switch_model(self, model_name):
        """P0-01: 热切换模型，立即生效，不重启"""
        if not model_name:
            return {"ok": False, "msg": "模型名不能为空"}
        try:
            self.config["local_model"] = model_name
            if self.trunk:
                self.trunk.config["local_model"] = model_name
                self.trunk.save_config()
            return {"ok": True, "model": model_name}
        except Exception as e:
            return {"ok": False, "msg": str(e)[:80]}

    def _watchdog(self):
        """监控空闲时间，自动卸载模型省内存"""
        while True:
            time.sleep(15)
            try:
                if self._unloaded: continue  # 已卸载就不重复
                if time.time() - self._last_call > self._idle_timeout:
                    with get_ollama_lock():
                        requests.post(self.base_url + "/api/generate",
                            json={"model": self.config.get("local_model", "xiao6-7b:latest"),
                                  "keep_alive": 0},  # 30分钟没聊才释放物理机模型
                            timeout=5)
                    self._unloaded = True
                    if self.trunk:
                        try: self.trunk._log("模型已自动卸载省内存")
                        except: pass
            except: pass

    def _touch(self):
        """记录调用时间"""
        self._last_call = time.time()
        self._unloaded = False  # 重新加载了

    def _load_config(self):
        if os.path.exists(self.config_path):
            try: return json.load(open(self.config_path, encoding="utf-8"))
            except: pass
        return {}

    def reload_config(self):
        """设置页改配置后热加载"""
        self.config = self._load_config()
        self.base_url = self.config.get("ollama_url", self.base_url)

    # ---------- 三级模型路由 ----------
    def _main_model(self):
        return self.config.get("local_model", "xiao6-7b:latest")

    def _small_model(self):
        return self.config.get("local_model", "xiao6-qwen3.5-4b:latest")

    def _vl_model(self):
        return self.config.get("local_model", "xiao6-qwen3.5-4b:latest")

    @staticmethod
    def _extract_user_text(message):
        """从 str 或 messages list 中取最后一条 user 文本"""
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            for m in reversed(message):
                if isinstance(m, dict) and m.get("role") == "user":
                    return str(m.get("content", ""))
            return str(message)
        return str(message)

    @staticmethod
    def _has_image(message):
        """messages list 中任一条带非空 images 字段（Ollama 视觉消息）"""
        if isinstance(message, list):
            for m in message:
                if isinstance(m, dict) and m.get("images"):
                    return True
        return False

    def _pick_model(self, message):
        """P1-1: 三级智能选模型：带图→VL；简单短消息→小模型；复杂→主力"""
        # 1. 带图片 → VL 视觉模型
        if self._has_image(message):
            return self._vl_model()
        # 2. 取用户文本
        text = self._extract_user_text(message)
        # 3. 简单问候/短消息 → 小模型
        simple_max = 15
        try:
            if self.trunk:
                simple_max = self.trunk.rule("路由.简单长度", 15)
        except Exception:
            pass
        if len(text.strip()) <= simple_max:
            return self._small_model()
        # 4. 其余 → 主力模型
        return self._main_model()

    # ---------- 对外入口 ----------
    def chat(self, message, inject_persona=True, force_model=None):
        """聊天。message 可为 str 或 messages list。
        inject_persona=False 时不注入小6人格（群聊子角色用自己的人设）；
        force_model 指定模型名时跳过路由（群聊角色固定主力模型）。"""
        self._touch()
        if _is_cloud_mode(self.config.get("model_mode", "本地路由")):
            return self._chat_cloud_only(message)
        return self._chat_local_route(message, inject_persona, force_model)

    def _chat_cloud_only(self, message):
        """模式②：只连云端，失败重试1次"""
        for attempt in range(2):
            r = self._try_cloud(message)
            if r:
                return r
            time.sleep(1)
        return "（云端模型暂时没响应，请检查网络或API密钥）"

    def _chat_local_route(self, message, inject_persona=True, force_model=None):
        """模式①：路由选模型 → 本地；路由模型挂了回退主力；本地全挂云端兜底"""
        main_model = self._main_model()
        picked = force_model or self._pick_model(message)
        # 复杂/带图 → 云端直连（失败回本地主力，不再白等本地超时）
        if picked == "__cloud__":
            cr = self._try_cloud(message)
            if cr:
                if self.trunk:
                    self.trunk._log("复杂/带图问题已由云端处理")
                return cr
            if self.trunk:
                self.trunk._log("云端失败，回退本地主力模型")
            picked = main_model
        orig = self.config.get("local_model")
        try:
            self.config["local_model"] = picked
            r = self._try_local(message, inject_persona)
            # 路由到小模型/VL 却失败（如 VL 未安装）→ 换主力模型重试
            if (not r or str(r).startswith("本地模型错误")) and picked != main_model:
                if self.trunk:
                    self.trunk._log("路由模型 %s 不可用，回退主力 %s" % (picked, main_model))
                self.config["local_model"] = main_model
                r = self._try_local(message, inject_persona)
            # 本地仍失败 → 云端兜底
            if not r or str(r).startswith("本地模型错误"):
                cr = self._try_cloud(message)
                if cr:
                    if self.trunk:
                        self.trunk._log("本地不可用，已由云端兜底")
                    return cr
            return r or "（抱歉，模型暂时没响应，请稍后再试）"
        finally:
            self.config["local_model"] = orig

    def _try_local(self, message, inject_persona=True):
        try:
            model = self.config.get("local_model", "xiao6-7b:latest")
            # 如果已经是list，直接用（消息 dict 内的 images 字段会随 JSON 一并发送给视觉模型）
            if isinstance(message, list):
                msgs = message
            else:
                msgs = [{"role": "user", "content": message}]

            # 注入拟人提示：兼容旧名 l45_personality → 新名 personality
            if inject_persona:
                try:
                    pers = None
                    if self.trunk:
                        pers = (self.trunk.modules.get("personality")
                                or self.trunk.modules.get("l45_personality"))
                        if not pers and hasattr(self.trunk, "_load_lazy"):
                            pers = self.trunk._load_lazy("personality")
                    if pers:
                        user_text = self._extract_user_text(msgs)
                        hint = pers.full_hint(user_text)
                        if hint:
                            sys_msg = {"role": "system",
                                       "content": "你是小6，住在用户电脑里的AI朋友。" + hint}
                            # 保留非 system 消息，去掉旧的 system
                            msgs = [sys_msg] + [m for m in msgs if m.get("role") != "system"]
                except Exception:
                    pass

            # 本地生成超时 120s：qwen3 思考型模型（xiao6-qwen3-4b）首次生成含思考+正文，60s 会误杀
            # 读超时（生成慢）→ 本地重试一次（模型冷启动/慢机常见）；连接失败 → 直接云兜底
            _t_out = 120
            _t0 = time.time()
            # 温度按场景：编程/代码问题0.3更准，闲聊0.7
            _ut = self._extract_user_text(msgs)
            _t = 0.3 if any(k in _ut for k in ("代码","bug","报错","函数","python","编程","脚本","程序","错误","修复")) else 0.7
            try:
                with get_ollama_lock():
                    r = requests.post(self.base_url + "/api/chat",
                        json={"model": model, "messages": msgs, "stream": False,
                              "think": False,
                              "keep_alive": "2h",
                              "options": {"num_ctx": 4096, "temperature": _t}},
                        timeout=_t_out)
                    self._fail_count = 0
                    _dt = time.time() - _t0
                    if self.trunk and _dt > 3:
                        self.trunk._log("本地回复 %.1fs" % _dt)
                    return r.json().get("message", {}).get("content", "")
            except requests.exceptions.ReadTimeout:
                # 生成超过 120s：可能正在冷加载模型，重试一次
                try:
                    with get_ollama_lock():
                        r = requests.post(self.base_url + "/api/chat",
                            json={"model": model, "messages": msgs, "stream": False,
                                  "think": False,
                                  "keep_alive": "2h"},
                            timeout=_t_out)
                        return r.json().get("message", {}).get("content", "")
                except Exception as e2:
                    if self.trunk: self.trunk._log("本地模型重试失败(%s): %s" % (model, str(e2)[:60]))
                    self._fail_count += 1
                    return "本地模型错误: " + str(e2)[:50]
        except Exception as e:
            self._fail_count += 1
            if self.trunk: self.trunk._log("本地模型失败，切云端: %s" % str(e)[:60])
            # 识别 Ollama 未启动
            _estr = str(e)
            if "ConnectionError" in _estr or "Connection refused" in _estr or "11434" in _estr:
                self.ollama_down = True
            # 自动降级：本地崩了走云端
            try:
                cloud = self._try_cloud(msgs)
                if cloud: return cloud
            except Exception: pass
            if "ConnectionError" in _estr or "Connection refused" in _estr:
                return "⚠ 连不上本地 Ollama（11434 端口）。\n请确认 Ollama 已启动，或在设置里切换到云端模型。"
            return "⚠ 本地模型出错: " + str(e)[:80]

    def _try_cloud(self, message):
        url = self.config.get("cloud_url", "")
        key = self.config.get("cloud_key", "")
        if not url or not key: return None
        model = self.config.get("cloud_model", "qwen-turbo")
        try:
            if isinstance(message, list):
                msgs = [{k: v for k, v in m.items() if k != "images"} if isinstance(m, dict) else m
                        for m in message]
            else:
                msgs = [{"role": "user", "content": message}]
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
            r = requests.post(url,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": model, "messages": msgs, "temperature": 0.7},
                timeout=30)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            if self.trunk: self.trunk._log("云端模型失败: " + str(e)[:60])
            return None

    def _try_cloud_stream(self, message, on_token=None):
        """云端真流式：逐字返回"""
        url = self.config.get("cloud_url", "")
        key = self.config.get("cloud_key", "")
        if not url or not key: return ""
        model = self.config.get("cloud_model", "qwen-turbo")
        try:
            if isinstance(message, list):
                msgs = [{k: v for k, v in m.items() if k != "images"} if isinstance(m, dict) else m
                        for m in message]
            else:
                msgs = [{"role": "user", "content": message}]
            if not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
            full = ""
            r = requests.post(url,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": model, "messages": msgs, "stream": True},
                stream=True, timeout=120)
            for line in r.iter_lines():
                if not line: continue
                line = line.decode("utf-8").strip()
                if not line.startswith("data:"): continue
                data = line[5:].strip()
                if data == "[DONE]": break
                try:
                    chunk = json.loads(data)
                    tok = chunk["choices"][0].get("delta", {}).get("content", "")
                    if tok:
                        full += tok
                        if on_token: on_token(tok)
                except: pass
            return full
        except Exception as e:
            if self.trunk: self.trunk._log("云端流式失败: " + str(e)[:60])
            return ""

    def stream_chat(self, message, on_token=None, force_model=None):
        """真流式：/api/chat stream=True 逐块接收，首字秒出；失败回退非流式"""
        try:
            model = force_model or self._pick_model(message)
            # 云端路径：无流式，直接一次性返回
            if model == "__cloud__":
                full = self._try_cloud(message)
                if full:
                    if on_token: on_token(full)
                    return full
                model = self._main_model()
            if isinstance(message, list):
                msgs = message
            else:
                msgs = [{"role": "user", "content": message}]
            full = ""
            try:
                with get_ollama_lock():  # 串行排队（流式持锁期间后台同样禁止并发，避免排队）
                    _ut2 = self._extract_user_text(msgs)
                    _t2 = 0.3 if any(k in _ut2 for k in ("代码","bug","报错","函数","python","编程","脚本","程序","错误","修复")) else 0.7
                    r = requests.post(self.base_url + "/api/chat",
                        json={"model": model, "messages": msgs, "stream": True,
                              "think": False,
                              "keep_alive": "2h",
                              "options": {"num_ctx": 4096, "temperature": _t2}},
                        stream=True, timeout=120)
                    for line in r.iter_lines():
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        tok = (d.get("message") or {}).get("content", "") or ""
                        if tok:
                            full += tok
                            if on_token:
                                on_token(tok)
                        if d.get("done"):
                            break
            except requests.exceptions.ReadTimeout:
                if on_token and not full:
                    on_token("（本地超时，切云端...）")
                    full = self._try_cloud_stream(msgs, on_token=on_token)
            except requests.exceptions.ConnectionError as e:
                if self.trunk:
                    self.trunk._log("本地连接失败(流式): %s" % str(e)[:40])
                if on_token and not full:
                    on_token("（本地模型连接失败，稍后自动用云端）")
            # 兜底：流式异常但什么都没收到时，非流式重试一次
            if not full:
                r2 = self.chat(msgs)
                if r2 and not str(r2).startswith("本地模型错误"):
                    full = str(r2)
                    if on_token and full:
                        for ch in full:
                            on_token(ch)
            return full
        except Exception as e:
            if on_token: on_token("（模型错误：" + str(e)[:30] + "）")
            return ""

    def run(self, message="你好"):
        return self.chat(message)

    def get_model_info(self):
        """获取当前模型信息"""
        return {
            "模式": self.config.get("model_mode", "本地路由"),
            "本地模型": self.config.get("local_model", "?"),
            "云端模型": self.config.get("cloud_model", "?"),
            "Ollama状态": "离线" if self.ollama_down else "在线",
        }

    def switch_mode(self, mode):
        """切换模式（本地/云端）
        优先走躯干原子写（保持配置单一事实源）；无躯干时本地兜底写入。"""
        self.config["model_mode"] = mode
        try:
            if self.trunk and hasattr(self.trunk, "save_config"):
                # 同步到躯干 config 后再原子写，保证 config.json 一致
                self.trunk.config["model_mode"] = mode
                self.trunk.save_config()
            else:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self.trunk:
                try:
                    self.trunk._log("switch_mode 保存失败: " + str(e)[:60])
                except Exception:
                    pass
        return {"成功": True, "当前模式": mode}

    def get_stats(self):
        """调用统计"""
        return {
            "连续失败次数": self._fail_count,
            "Ollama离线": self.ollama_down,
        }

    def reset_fail_count(self):
        """重置失败计数"""
        self._fail_count = 0
        return {"成功": True}

