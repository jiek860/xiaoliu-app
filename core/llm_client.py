# -*- coding: utf-8 -*-
"""L模块 v8.0 - llm_client
两种模式：
  ① 本地路由：三级智能选模型——简单问候→小模型，日常→主力7b，带图/复杂→视觉VL；
     本地（含回退主力）失败后云端兜底。
  ② 云端模型：只连云端。
群聊子角色可用 force_model 固定模型，不参与路由。"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json, os, requests, time, re, threading, weakref

from core.secret_store import decrypt_config, encrypt_config

# 活着的 LLMClient（2026-10-28）：
# 看门狗线程持有 self 的绑定方法 → 客户端不会被回收，测试里"造了又换掉"的实例
# （比如把 modules["llm"] 换成 FakeLLM）就一直挂着 `llm-watchdog`。
# 登记起来，让测试收尾能把它们统统 stop() 掉（截断累积，见 tests/conftest.py）。
_LIVE_CLIENTS = weakref.WeakSet()
_LIVE_LOCK = threading.Lock()


def live_clients():
    """当前还活着的 LLMClient 快照（测试收尾用）"""
    with _LIVE_LOCK:
        return list(_LIVE_CLIENTS)


def _is_cloud_mode(mode):
    m = str(mode).lower()
    return ("云端" in str(mode)) or ("cloud" in m)


from core.llm_shared import get_ollama_lock, config_seconds
from core.llm_health import LLMHealthMixin
from core.llm_usage import LLMUsageMixin
from core.llm_cloud import LLMCloudMixin
from core.llm_local import LLMLocalMixin


class LLMClient(
    LLMHealthMixin,
    LLMUsageMixin,
    LLMCloudMixin,
    LLMLocalMixin,
):
    def __init__(self, trunk=None, defer_warmup=False, **kwargs):
        # defer_warmup=True：只做内存初始化，看门狗和预热交给调用方调度，
        # 用于启动阶段（实测能省 20~30ms 且避免和 GUI 首帧抢 CPU）。
        kwargs_defer = bool(defer_warmup or kwargs.get("defer_warmup"))
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
        self._model_cooldown = {}
        self._model_fail_counts = {}
        # 看门狗线程的退出标志（2026-10-28）：
        # `_watchdog` 原来是 `while True: sleep(15)`，没有任何出口 ——
        # 关窗/换躯干后线程留在原地，测试里每造一个 LLMClient 就多一个
        # `llm-watchdog`（实测全量跑到 5 个，累积效应见 trunk_background 的登记表说明）。
        self._stop_event = threading.Event()
        from core.response_cache import ResponseCache
        self._response_cache = ResponseCache(ttl=300, max_items=128)
        # P2-2: 用requests.Session复用连接，提升性能
        import requests as _req
        self._session = _req.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        # 看门狗/预热都延后启动：它们要 import requests 之外的重库、还要发网络
        # 请求，放在构造函数里会直接拖慢 Trunk 创建（启动阶段最贵的路径）。
        # defer_warmup=True 时由 Trunk 在后台统一调度（见 trunk 的 _warmup）。
        if not kwargs_defer:
            self.start_background_workers()
            threading.Thread(target=self._warmup, daemon=True).start()
        # 登记：线程持有 self，不登记的话"造了又换掉"的实例会一直挂着看门狗
        with _LIVE_LOCK:
            _LIVE_CLIENTS.add(self)

    def start_background_workers(self):
        """启动看门狗线程（幂等）。defer_warmup=True 时由上层在启动完成后调用。"""
        if getattr(self, "_timer_running", False):
            return False
        # stop() 之后不许再起：躯干关窗时先 stop，而 `llm-warmup-timer` 可能
        # 还在 1 秒倒计时里，到点会调到这里。以前没有这道闸，于是"停了又活"，
        # 测试收尾后仍能看到孤零零的 llm-watchdog（实测残留 1~2 个）。
        if getattr(self, "_stop_event", None) is not None and self._stop_event.is_set():
            return False
        self._timer = threading.Thread(target=self._watchdog, daemon=True,
                                       name="llm-watchdog")
        self._timer.start()
        self._timer_running = True
        return True

    def stop(self):
        """停看门狗线程并断开连接池（trunk.shutdown / 测试收尾调用）"""
        try:
            self._stop_event.set()
        except Exception as e:  # 静默是故意的 - 没起过线程也不影响退出
            _x6_swallowed(__name__, e, "stop llm watchdog")
        self._timer_running = False
        try:
            self._session.close()
        except Exception as e:  # 静默是故意的 - 连接池关不掉不影响退出
            _x6_swallowed(__name__, e, "close llm session")
        with _LIVE_LOCK:
            _LIVE_CLIENTS.discard(self)
        return {"已停止": True}

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

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                return decrypt_config(
                    json.load(open(self.config_path, encoding="utf-8")))
            except Exception:
                return {}
        return {}

    def reload_config(self):
        """设置页改配置后热加载"""
        self.config = self._load_config()
        self.base_url = self.config.get("ollama_url", self.base_url)

    def chat(self, message, inject_persona=True, force_model=None):
        """聊天。message 可为 str 或 messages list。
        inject_persona=False 时不注入小6人格（群聊子角色用自己的人设）；
        force_model 指定模型名时跳过路由（群聊角色固定主力模型）。"""
        self._touch()
        if _is_cloud_mode(self.config.get("model_mode", "本地路由")):
            return self._chat_cloud_only(message)
        return self._chat_local_route(message, inject_persona, force_model)

    def chat_with_image(self, prompt, image_base64=None, image_path=None):
        """多模态聊天：带图片（OpenAI messages list 格式，真的传 base64）

        如果底层 API 支持多模态（如 GPT-4V、Claude 3），就能真的看图。
        如果不支持，会报错，调用方自己降级。
        """
        import base64

        # 如果只给了路径，读成 base64
        if image_path and not image_base64:
            try:
                with open(image_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception:  # 静默是故意的：图片读取失败时走纯文本降级
                pass

        if image_base64:
            # 真正的多模态格式：messages list 带 image_url
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
                    ]
                }
            ]
            try:
                return self.chat(messages)
            except Exception:  # 静默是故意的：多模态失败时降级纯文本
                # 多模态不支持，降级到纯文本
                pass

        # 降级：纯文本
        return self.chat(prompt)

    def stream_chat(self, message, on_token=None, force_model=None,
                    cancel_token=None):
        """真流式：/api/chat stream=True 逐块接收，首字秒出；失败回退非流式

        cancel_token：用户按 Esc 停止时，GUI 线程会置位并 close 流响应。
        这里每个分块前检查，取消后立刻停止，不再走云端兜底或非流式重试，
        从而及时释放 Ollama 串行锁（否则下一条消息会一直排队）。
        """
        full = ""

        def _cancelled():
            return bool(cancel_token is not None and cancel_token.is_cancelled())

        try:
            if _cancelled():
                return ""
            # 先看模式：设成"云端模型"就别碰本地。
            #
            # 这里原来只认 _pick_model() 返回 "__cloud__" 这个魔数，而
            # _pick_model 永远只返回本地模型名（VL/小模型/主力），从不返回它 ——
            # 那个分支是死代码。后果：设置里切成"云端模型"后，
            # chat() 照做了，但 GUI 的回复走的是带 on_token 的 stream_chat()，
            # 它完全不看 model_mode，每次回复都先去打本地 /api/chat
            # （timeout=120），等满两分钟才降级到云端 —— 这就是"切了云端还是很慢"。
            mode_cloud = _is_cloud_mode(self.config.get("model_mode", "本地路由"))
            if mode_cloud and not force_model:
                # 云端模式也要真流式，别再等整段答案生成完才一次性刷出来。
                full = self._try_cloud_stream(message, on_token=on_token,
                                              cancel_token=cancel_token)
                if _cancelled():
                    return full
                if not full:
                    # 少数兼容端点不支持 stream，退回一次性调用。
                    full = self._try_cloud(message)
                    if _cancelled():
                        return full
                    if full and on_token:
                        on_token(full)
                if full:
                    return full
                if on_token:
                    on_token("（云端模型没响应，试一下本地…）")
            model = force_model or self._pick_model(message)
            if model == "__cloud__":
                full = self._try_cloud_stream(message, on_token=on_token,
                                              cancel_token=cancel_token)
                if _cancelled():
                    return full
                if not full:
                    full = self._try_cloud(message)
                    if _cancelled():
                        return full
                    if full and on_token:
                        on_token(full)
                if full:
                    return full
                model = self._main_model()
            if isinstance(message, list):
                msgs = message
            else:
                msgs = [{"role": "user", "content": message}]
            full = ""
            _local_timeout = False
            try:
                with get_ollama_lock():  # 串行排队（流式持锁期间后台同样禁止并发，避免排队）
                    _ut2 = self._extract_user_text(msgs)
                    _t2 = 0.3 if any(k in _ut2 for k in ("代码","bug","报错","函数","python","编程","脚本","程序","错误","修复")) else 0.7
                    # 首字超时：本地模型卡住（模型加载/显存不足）时不要死等 120 秒，
                    # 超过阈值还没有第一个 token 就直接切云端；可在 config.json
                    # 用"本地首字超时" / local_first_token_timeout 调整（5~300 秒）。
                    _first_token = config_seconds(
                        self.config, ("本地首字超时", "local_first_token_timeout"), 25)
                    r = self._post(self.base_url + "/api/chat",
                        json={"model": model, "messages": msgs, "stream": True,
                              "think": False,
                              "keep_alive": "2h",
                              "options": {"num_ctx": 4096, "temperature": _t2}},
                        stream=True, timeout=(5, _first_token))
                    if cancel_token is not None:
                        # 关键：把流响应登记给取消方。Esc 时会在 GUI 线程
                        # 直接 close，叫醒阻塞中的 iter_lines，立刻释放连接与锁。
                        cancel_token.bind(r.close)
                    try:
                        for line in r.iter_lines():
                            if _cancelled():
                                break
                            if not line:
                                continue
                            try:
                                d = json.loads(line)
                            except Exception as e:
                                _x6_swallowed(__name__, e)
                                continue
                            tok = (d.get("message") or {}).get("content", "") or ""
                            if tok:
                                full += tok
                                if on_token:
                                    on_token(tok)
                            if d.get("done"):
                                break
                    finally:
                        try:
                            r.close()
                        except Exception as e:  # 静默是故意的：关闭失败不影响结果
                            _x6_swallowed(__name__, e, "close stream response")
                        if cancel_token is not None:
                            cancel_token.unbind(r.close)
            except requests.exceptions.ReadTimeout:
                _local_timeout = True
                if _cancelled():
                    return full
                if on_token and not full:
                    if self.trunk:
                        self.trunk._log("本地首字超时(%ss)，切云端" % _first_token)
                    on_token("（本地首字超时，切云端...）")
                    full = self._try_cloud_stream(msgs, on_token=on_token,
                                                  cancel_token=cancel_token)
            except requests.exceptions.ConnectionError as e:
                if _cancelled():
                    return full
                if self.trunk:
                    self.trunk._log("本地连接失败(流式): %s" % str(e)[:40])
                if on_token and not full:
                    on_token("（本地模型连接失败，稍后自动用云端）")
            except Exception as e:
                # 取消时跨线程 close 会让 iter_lines 抛出各种传输层异常，
                # 这不是真错误：保留已收到的内容，直接返回。
                if _cancelled():
                    return full
                raise
            # 兜底：流式异常但什么都没收到时，非流式重试一次。
            # 取消后不重试；本地刚首字超时也不重试（否则又白等一次本地）。
            if _cancelled():
                return full
            if not full and not _local_timeout:
                r2 = self.chat(msgs)
                if r2 and not str(r2).startswith("本地模型错误"):
                    full = str(r2)
                    if on_token and full:
                        for ch in full:
                            on_token(ch)
            return full
        except Exception as e:
            if _cancelled():
                return full
            if on_token: on_token("（模型错误：" + str(e)[:30] + "）")
            return ""

    def run(self, message="你好"):
        return self.chat(message)

    def route_request(self, requirements=None, local_failed=None):
        """Return a deterministic local/cloud model route for a task."""
        from core.model_router import TaskRequirements, route_model
        local_model = str(self.config.get("local_model", "") or "")
        cloud_model = str(self.config.get("cloud_model", "") or "")
        provider = str(self.config.get("cloud_provider") or "openai")
        return route_model(
            local_model=local_model, cloud_model=cloud_model,
            provider=provider,
            requirements=requirements or TaskRequirements(),
            local_available=not bool(getattr(self, "ollama_down", False)),
            local_failed=bool(self._fail_count >= 3 if local_failed is None
                              else local_failed),
        )

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
                _enc, _n = encrypt_config(self.config)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(_enc, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self.trunk:
                try:
                    self.trunk._log("switch_mode 保存失败: " + str(e)[:60])
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass
        return {"成功": True, "当前模式": mode}
