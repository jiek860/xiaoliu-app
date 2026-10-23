# -*- coding: utf-8 -*-
"""本地 Ollama 路由和调用。"""
from __future__ import annotations

import time
import requests
from core.llm_shared import _is_cloud_mode, get_ollama_lock

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class LLMLocalMixin:
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
    def _normalize_ollama_messages(message):
        """把 OpenAI 风格 content 列表转成 Ollama 的 text + images 字段。"""
        if not isinstance(message, list):
            return message
        out = []
        for m in message:
            if not isinstance(m, dict):
                out.append(m)
                continue
            content = m.get("content")
            if not isinstance(content, list):
                out.append(m)
                continue
            texts, images = [], []
            for item in content:
                if not isinstance(item, dict):
                    texts.append(str(item))
                    continue
                if item.get("type") == "text":
                    texts.append(str(item.get("text") or ""))
                elif item.get("type") in ("image_url", "image"):
                    u = item.get("image_url") or item.get("url") or ""
                    if isinstance(u, dict):
                        u = u.get("url") or ""
                    if str(u).startswith("data:") and ";base64," in str(u):
                        images.append(str(u).split(",", 1)[1])
            nm = dict(m)
            nm["content"] = "\n".join(texts)
            if images:
                nm["images"] = images
            out.append(nm)
        return out

    @staticmethod
    def _has_image(message):
        """messages list 中任一条带非空 images 字段或 image_url content。"""
        if isinstance(message, list):
            for m in message:
                if not isinstance(m, dict):
                    continue
                if m.get("images"):
                    return True
                content = m.get("content")
                if isinstance(content, list) and any(
                        isinstance(x, dict) and x.get("type") in
                        ("image_url", "image") for x in content):
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
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        if len(text.strip()) <= simple_max:
            return self._small_model()
        # 4. 其余 → 主力模型
        return self._main_model()

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
            if self._model_cooling(model):
                return "本地模型错误: 模型熔断中，请稍后重试"
            # 如果已经是list，直接用（消息 dict 内的 images 字段会随 JSON 一并发送给视觉模型）
            if isinstance(message, list):
                msgs = self._normalize_ollama_messages(message)
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
                except Exception as e:
                    _x6_swallowed(__name__, e)
                    pass

            msgs = self._fit_messages(msgs)
            # 本地生成超时 120s：qwen3 思考型模型（xiao6-qwen3-4b）首次生成含思考+正文，60s 会误杀
            # 读超时（生成慢）→ 本地重试一次（模型冷启动/慢机常见）；连接失败 → 直接云兜底
            _t_out = 120
            _t0 = time.time()
            # 温度按场景：编程/代码问题0.3更准，闲聊0.7
            _ut = self._extract_user_text(msgs)
            _t = 0.3 if any(k in _ut for k in ("代码","bug","报错","函数","python","编程","脚本","程序","错误","修复")) else 0.7
            try:
                with get_ollama_lock():
                    r = self._post(self.base_url + "/api/chat",
                        json={"model": model, "messages": msgs, "stream": False,
                              "think": False,
                              "keep_alive": "2h",
                              "options": {"num_ctx": 4096, "temperature": _t}},
                        timeout=_t_out)
                    self._fail_count = 0
                    _dt = time.time() - _t0
                    if self.trunk and _dt > 3:
                        self.trunk._log("本地回复 %.1fs" % _dt)
                    _ans = r.json().get("message", {}).get("content", "")
                    self._mark_model_success(model)
                    self._track_usage(model, msgs, _ans, _dt, kind="local_model")
                    return _ans
            except requests.exceptions.ReadTimeout:
                # 生成超过 120s：可能正在冷加载模型，重试一次
                try:
                    with get_ollama_lock():
                        r = self._post(self.base_url + "/api/chat",
                            json={"model": model, "messages": msgs, "stream": False,
                                  "think": False,
                                  "keep_alive": "2h"},
                            timeout=_t_out)
                        return r.json().get("message", {}).get("content", "")
                except Exception as e2:
                    if self.trunk: self.trunk._log("本地模型重试失败(%s): %s" % (model, str(e2)[:60]))
                    self._fail_count += 1
                    self._mark_model_failure(model, e2)
                    return "本地模型错误: " + str(e2)[:50]
        except Exception as e:
            self._fail_count += 1
            try:
                self._mark_model_failure(self.config.get("local_model", "?"), e)
            except Exception as e:  # 静默是故意的 - 熔断计数失败不阻断云端回退
                _x6_swallowed(__name__, e, "best-effort fallback")
            if self.trunk: self.trunk._log("本地模型失败，切云端: %s" % str(e)[:60])
            # 识别 Ollama 未启动
            _estr = str(e)
            if "ConnectionError" in _estr or "Connection refused" in _estr or "11434" in _estr:
                self.ollama_down = True
            # 自动降级：本地崩了走云端
            try:
                cloud = self._try_cloud(msgs)
                if cloud: return cloud
            except Exception as e:
                _x6_swallowed(__name__, e)
            if "ConnectionError" in _estr or "Connection refused" in _estr:
                return "⚠ 连不上本地 Ollama（11434 端口）。\n请确认 Ollama 已启动，或在设置里切换到云端模型。"
            return "⚠ 本地模型出错: " + str(e)[:80]
