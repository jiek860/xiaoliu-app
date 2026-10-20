# -*- coding: utf-8 -*-
"""LLM 用量统计、上下文裁剪和响应缓存。"""
from __future__ import annotations

import json
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class LLMUsageMixin:
    def _track_usage(self, model, messages, answer, elapsed=0.0,
                     kind="llm", success=True):
        try:
            from core.usage_tracker import UsageTracker
            text = self._extract_user_text(messages)
            tin = max(1, len(str(text)) // 4)
            tout = max(1, len(str(answer)) // 4)
            from core.model_pricing import estimate_cost
            cost = estimate_cost(model, tin, tout,
                                 (self.config or {}).get("model_prices"))
            UsageTracker(self.base).record(
                kind=kind, name="chat", model=str(model),
                tokens_in=tin, tokens_out=tout, cost=cost,
                elapsed=float(elapsed or 0), success=success)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _fit_messages(self, messages):
        try:
            from core.context_budget import trim_messages
            limit = int((self.config or {}).get("context_token_budget", 6000))
            return trim_messages(messages, max_tokens=limit)
        except Exception:
            return messages

    def _cache_key(self, message, inject_persona, force_model):
        mode = (self.config or {}).get("model_mode", "本地路由")
        return self._response_cache.key(repr(message), bool(inject_persona),
                                        force_model or "", mode)

    def clear_response_cache(self):
        self._response_cache.clear()
        return {"ok": True}

    def get_stats(self):
        """调用统计"""
        return {
            "连续失败次数": self._fail_count,
            "Ollama离线": self.ollama_down,
        }
