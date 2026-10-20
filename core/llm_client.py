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

import json, os, requests, time, re, threading

from core.secret_store import decrypt_config, encrypt_config

def _is_cloud_mode(mode):
    m = str(mode).lower()
    return ("云端" in str(mode)) or ("cloud" in m)


from core.llm_shared import get_ollama_lock
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
        self._model_cooldown = {}
        self._model_fail_counts = {}
        from core.response_cache import ResponseCache
        self._response_cache = ResponseCache(ttl=300, max_items=128)
        # P2-2: 用requests.Session复用连接，提升性能
        import requests as _req
        self._session = _req.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._timer = threading.Thread(target=self._watchdog, daemon=True)
        self._timer.start()
        # 模型预热：后台线程先加载模型，第一次聊天不等冷加载
        threading.Thread(target=self._warmup, daemon=True).start()

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

    def stream_chat(self, message, on_token=None, force_model=None):
        """真流式：/api/chat stream=True 逐块接收，首字秒出；失败回退非流式"""
        try:
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
                full = self._try_cloud(message)
                if full:
                    if on_token:
                        on_token(full)
                    return full
                if on_token:
                    on_token("（云端模型没响应，试一下本地…）")
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
                    r = self._post(self.base_url + "/api/chat",
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
