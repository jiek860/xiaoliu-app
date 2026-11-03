# -*- coding: utf-8 -*-
"""LLM 云端调用、流式、脱敏和响应缓存辅助。"""
from __future__ import annotations

import time
import requests
from core.llm_shared import _is_cloud_mode, config_seconds

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _plain_cloud_key(value):
    """cloud_key 兜底解密。

    `core.config.load_config()` 读配置时已经把 DPAPI 密文解开了，
    这里只是防"某条路径拿到的是密文"：把 `dpapi:v1:...` 当 Bearer
    发出去，服务端只会回 401「令牌已过期或验证不正确」，看起来像
    Key 失效，实际是密文被当成了明文。
    """
    try:
        from core.model_setup import _plain_key
        return _plain_key(value)
    except Exception as e:
        _x6_swallowed(__name__, e, "best-effort fallback")
        return str(value or "")


def _is_local_target(url, base_url=""):
    """判断请求目标是不是"本机服务"（本地模型 / 本地 MCP）。

    为什么不能只比较 startswith(base_url)
    ------------------------------------
    真实故障（2026-10-22 日志）：
        "本地模型失败，切云端: 私有/回环/保留地址"
    原因是 base_url 配的是 127.0.0.1，而实际请求发往 localhost，
    startswith 对不上 -> 被当成 cloud_model -> 网络守卫把回环地址拒了
    -> 本地模型永远不可用，只能一直走云端。

    这里改成按**目标主机**判断：只要 host 是回环/本机，就按 local 处理，
    与 base_url 的写法（127.0.0.1 / localhost / ::1，带不带端口）无关。
    """
    import urllib.parse
    try:
        host = (urllib.parse.urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return False
    # 这里是**判断**请求目标是不是本机，不是在绑定监听地址（Bandit 误报）。
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):  # nosec B104
        return True
    base = str(base_url or "").strip()
    return bool(base) and str(url or "").startswith(base)


def local_model_purpose(trunk, url):
    """判断一次请求该用哪个网络 purpose。

    只要目标主机是本机（回环）**或**用户在本地模型配置里填的那台机器
    （典型：虚拟机连物理机的 Ollama），就按 local_model 处理，
    否则按 cloud_model。

    这一点很关键：purpose 决定了网络守卫是否放行私有地址。
    用错就会像之前那样"本地模型永远失败，一直切云端"。
    """
    import urllib.parse
    try:
        host = (urllib.parse.urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return "cloud_model"
    if host in ("127.0.0.1", "localhost", "::1"):
        return "local_model"
    cfg = getattr(trunk, "config", {}) or {}
    for key in ("ollama_url", "local_url", "local_base_url"):
        raw = str(cfg.get(key) or "")
        if not raw:
            continue
        try:
            c_host = (urllib.parse.urlparse(raw).hostname or "").lower()
        except ValueError:
            continue
        if c_host and c_host == host:
            return "local_model"
    return "cloud_model"


class LLMCloudMixin:
    def _post(self, url, **kwargs):
        """所有 requests.post 的统一出口，先过网络策略。"""
        try:
            from core.net_guard import get_net_guard
            purpose = local_model_purpose(getattr(self, "trunk", None), url)
            d = get_net_guard(self.trunk).check(
                url, module="llm_client", purpose=purpose, method="POST")
            if not d.get("allow"):
                if self.trunk:
                    self.trunk._log("网络策略拒绝: %s (%s)" %
                                    (d.get("reason"), d.get("domain", "")))
                raise PermissionError(d.get("reason") or "网络请求被拒绝")
        except PermissionError:
            raise
        except Exception as e:
            # 网络策略自身异常时，外部请求按拒绝处理；本地模型按本地放行，
            # 避免把程序自己的异常变成 Ollama 不可用。
            if "localhost" in str(url) or "127.0.0.1" in str(url):
                pass
            else:
                raise PermissionError("网络策略检查失败: %s" % str(e)[:60]) from e
        kwargs.setdefault("timeout", 60)
        return requests.post(url, **kwargs)  # nosec B113

    @staticmethod
    def _cloud_user_text(msgs):
        """取最后一条 user 文本（不依赖 LLMLocalMixin，便于单测）。"""
        if isinstance(msgs, str):
            return msgs
        for m in reversed(list(msgs or [])):
            if not isinstance(m, dict) or str(m.get("role")) != "user":
                continue
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(str(x.get("text") or "") for x in content
                                if isinstance(x, dict))
        return ""

    def _cloud_options(self, msgs, provider=""):
        """云端采样参数（第 2 批）：场景默认 ← 模型推荐 ← 用户覆盖。

        按服务商做参数名映射（gemini 的 top_p 叫 topP，anthropic 不认
        frequency_penalty），不支持的项直接丢掉 —— 发过去会被 400。
        """
        try:
            from core.context_window import cloud_options, sampling_for
            params = sampling_for(self.config, self._cloud_user_text(msgs),
                                  model=self.config.get("cloud_model", ""))
            return cloud_options(params, provider or "openai")
        except Exception as e:
            _x6_swallowed(__name__, e, "cloud sampling options")
            return {}

    def _provider_request(self, messages, stream=False, timeout=30, options=None):
        """Build a provider-specific request when cloud_provider is configured."""
        provider = str(self.config.get("cloud_provider") or "").strip()
        if not provider:
            return None
        from core.llm_providers import (
            build_chat_request, config_for_provider, normalize_provider,
            provider_spec)
        key = normalize_provider(provider)
        spec = provider_spec(key)
        connector = config_for_provider(self.config, key)
        connector["api_key"] = _plain_cloud_key(connector.get("api_key"))
        if not spec:
            raise ValueError("unknown cloud provider: %s" % provider)
        if not connector["local"] and not connector["api_key"]:
            raise ValueError("provider requires cloud_key")
        if not connector["base_url"]:
            raise ValueError("provider requires cloud_url/base_url")
        return build_chat_request(
            key, connector["model"], messages,
            api_key=connector["api_key"], base_url=connector["base_url"],
            stream=stream, options=options,
            deployment=connector["deployment"],
            api_version=connector["api_version"])

    def _chat_cloud_only(self, message):
        """模式②：只连云端，失败重试1次"""
        for _attempt in range(2):
            r = self._try_cloud(message)
            if r:
                return r
            time.sleep(1)
        return "（云端模型暂时没响应，请检查网络或API密钥）"

    def _mask_if_enabled(self, msgs):
        """发云端前按需脱敏（sensitive_detector）

        默认**关闭**：自动脱敏会改变真正发出去的内容
        （比如你问"这个身份证号对不对"会被打成 110***********234），
        所以做成开关，用户自己在 config.json 里加 "云端脱敏": true 才生效。
        sensitive_detector 这个模块登记了很久没人调用，这里给它接上。
        """
        try:
            if not self.config.get("云端脱敏", False):
                return msgs
            if self.trunk is None:
                return msgs
            if "sensitive_detector" not in self.trunk.modules:
                self.trunk.call("sensitive_detector", "__no__")
            sd = self.trunk.modules.get("sensitive_detector")
            if sd is None or not hasattr(sd, "mask"):
                return msgs
            out = []
            for m in msgs:
                if isinstance(m, dict) and isinstance(m.get("content"), str):
                    m = dict(m)
                    m["content"] = sd.mask(m["content"])
                out.append(m)
            return out
        except Exception:
            return msgs

    def _try_cloud(self, message):
        url = self.config.get("cloud_url", "")
        key = _plain_cloud_key(self.config.get("cloud_key", ""))
        model = self.config.get("cloud_model", "qwen-turbo")
        try:
            if isinstance(message, list):
                msgs = [{k: v for k, v in m.items() if k != "images"} if isinstance(m, dict) else m
                        for m in message]
            else:
                msgs = [{"role": "user", "content": message}]
            msgs = self._fit_messages(self._mask_if_enabled(msgs))
            _t0 = time.time()
            _opts = self._cloud_options(
                msgs, self.config.get("cloud_provider") or "")
            provider_req = self._provider_request(msgs, stream=False, timeout=30,
                                                  options=_opts)
            if provider_req is not None:
                r = self._post(provider_req["url"], headers=provider_req["headers"],
                               json=provider_req["json"], timeout=30)
                from core.llm_providers import parse_chat_response
                _ans = parse_chat_response(provider_req["provider"], r.json())
            else:
                if not url or not key:
                    return None
                if not url.endswith("/chat/completions"):
                    url = url.rstrip("/") + "/chat/completions"
                _body = {"model": model, "messages": msgs}
                _body.update(_opts or {"temperature": 0.7})
                r = self._post(url,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    json=_body,
                    timeout=30)
                _ans = r.json()["choices"][0]["message"]["content"]
            self._track_usage(model, msgs, _ans, time.time() - _t0,
                              kind="cloud_model")
            return _ans
        except Exception as e:
            if self.trunk: self.trunk._log("云端模型失败: " + str(e)[:60])
            return None

    def _try_cloud_stream(self, message, on_token=None, cancel_token=None):
        """云端真流式：逐字返回（provider 适配 + 可取消）

        之前配置了 cloud_provider 时会退回非流式 ``_try_cloud``，界面上
        要等整段答案生成完才一次性刷出来。这里改为按 provider 发流式请求，
        统一用 ``parse_stream_chunk`` 取 token（openai/azure/anthropic/gemini）。

        cancel_token：Esc 时 GUI 线程会 close 流响应，叫醒阻塞中的 iter_lines；
        每块前再检查一次，取消后立刻返回已收到内容，不再写错误提示。
        """
        url = self.config.get("cloud_url", "")
        key = _plain_cloud_key(self.config.get("cloud_key", ""))
        model = self.config.get("cloud_model", "qwen-turbo")

        def _cancelled():
            return bool(cancel_token is not None and cancel_token.is_cancelled())

        if isinstance(message, list):
            msgs = [{k: v for k, v in m.items() if k != "images"} if isinstance(m, dict) else m
                    for m in message]
        else:
            msgs = [{"role": "user", "content": message}]
        # 云端流式也必须遵守云端脱敏配置，不能绕过 _try_cloud 的脱敏。
        msgs = self._fit_messages(self._mask_if_enabled(msgs))
        if _cancelled():
            return ""
        full = ""
        _t0 = time.time()
        r = None
        guard = None
        _stalled = False
        try:
            _opts = self._cloud_options(
                msgs, self.config.get("cloud_provider") or "")
            provider_req = self._provider_request(msgs, stream=True, timeout=30,
                                                  options=_opts)
            if provider_req is not None:
                req_url = provider_req["url"]
                req_headers = provider_req["headers"]
                req_json = provider_req["json"]
                provider = provider_req["provider"]
            else:
                if not url or not key:
                    return ""
                if not url.endswith("/chat/completions"):
                    url = url.rstrip("/") + "/chat/completions"
                req_url = url
                req_headers = {"Authorization": "Bearer " + key,
                               "Content-Type": "application/json"}
                req_json = {"model": model, "messages": msgs, "stream": True}
                req_json.update(_opts or {"temperature": 0.7})
                provider = "openai"
            from core.llm_providers import parse_stream_chunk
            _first_timeout = config_seconds(
                self.config, ("云端首字超时", "cloud_first_token_timeout"), 60)
            r = self._post(req_url, headers=req_headers, json=req_json,
                           stream=True, timeout=(10, _first_timeout))
            if cancel_token is not None:
                cancel_token.bind(r.close)
            # 中途卡顿看门狗（第 3 批深度⑦）：read timeout 每次 read 重计时，
            # 服务端只要偶尔发个心跳就永不超时，界面会一直"正在输入"。
            try:
                from core.stream_guard import StreamStallGuard, guard_seconds
                guard = StreamStallGuard(
                    guard_seconds(self.config),
                    on_stall=lambda g: self.trunk and self.trunk._log(
                        "云端流式中途卡顿 %ss，已断流" % int(g.seconds)))
                guard.bind(r).start()
            except Exception as e:
                _x6_swallowed(__name__, e, "cloud stall guard init")
            try:
                for line in r.iter_lines():
                    if guard is not None:
                        guard.touch()
                    if _cancelled():
                        break
                    if not line:
                        continue
                    line = line.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    tok = parse_stream_chunk(provider, data)
                    if tok:
                        full += tok
                        if on_token:
                            on_token(tok)
            finally:
                if guard is not None:
                    _stalled = guard.stalled
                    guard.stop()
            if _stalled:
                # 卡顿不是真错误：已收到的内容照样返回，下次对话再不受影响
                if self.trunk:
                    self.trunk._log("云端流式中途卡顿，已收到 %d 字，停止等待"
                                    % len(full))
            if full:
                self._track_usage(model, msgs, full, time.time() - _t0,
                                  kind="cloud_model_stream")
            return full
        except Exception as e:
            # 取消导致的传输层异常不是真错误：保留已收到内容直接返回。
            if _cancelled():
                return full
            # 中途卡顿时是我们自己 close 流，异常由此而来，不算失败
            if guard is not None and guard.stalled:
                if self.trunk:
                    self.trunk._log("云端流式中途卡顿，已收到 %d 字，停止等待"
                                    % len(full))
                return full
            if self.trunk: self.trunk._log("云端流式失败: " + str(e)[:60])
            return full
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception as e:  # 静默是故意的：关闭失败不影响结果
                    _x6_swallowed(__name__, e, "close cloud stream")
                if cancel_token is not None:
                    cancel_token.unbind(r.close)
