# -*- coding: utf-8 -*-
"""LLM 健康检查、预热、冷却和故障计数。"""
from __future__ import annotations

import time
from core.llm_shared import _is_cloud_mode, get_ollama_lock

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class LLMHealthMixin:
    def _warmup(self):
        """启动时后台预热模型（只在用本地模型时做）"""
        try:
            # 云端模式下不预热本地：
            #   · 预热是为了让第一次聊天不等模型冷加载，走云端时用不上
            #   · 它会持 get_ollama_lock() 最多 30 秒，而 vector_store._embed
            #     也要这把锁 —— 本地推理挂掉时，这个预热会把嵌入检索一起拖住
            if _is_cloud_mode(self.config.get("model_mode", "本地路由")):
                return
            time.sleep(2)
            with get_ollama_lock():
                self._post(self.base_url + "/api/chat",
                    json={"model": self._main_model(), "messages": [{"role":"user","content":"hi"}],
                          "stream": False, "keep_alive": "2h",
                          "options": {"num_ctx": 4096}},
                    timeout=30)
            if self.trunk: self.trunk._log("模型预热完成")
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _watchdog(self):
        """监控空闲时间，自动卸载模型省内存"""
        while True:
            time.sleep(15)
            try:
                if self._unloaded: continue  # 已卸载就不重复
                if time.time() - self._last_call > self._idle_timeout:
                    with get_ollama_lock():
                        self._post(self.base_url + "/api/generate",
                            json={"model": self.config.get("local_model", "xiao6-7b:latest"),
                                  "keep_alive": 0},  # 30分钟没聊才释放物理机模型
                            timeout=5)
                    self._unloaded = True
                    if self.trunk:
                        try: self.trunk._log("模型已自动卸载省内存")
                        except Exception as e:
                            _x6_swallowed(__name__, e)
            except Exception as e:
                _x6_swallowed(__name__, e)

    def _model_cooling(self, model):
        return float(self._model_cooldown.get(str(model), 0)) > time.time()

    def _mark_model_failure(self, model, reason=""):
        m = str(model)
        n = int(self._model_fail_counts.get(m, 0)) + 1
        self._model_fail_counts[m] = n
        if n >= 2:
            self._model_cooldown[m] = time.time() + min(300, 30 * n)
        try:
            from core.usage_tracker import UsageTracker
            UsageTracker(self.base).record(
                kind="model_failure", name="router", model=m,
                elapsed=0.0, success=False)
        except Exception as e:  # 静默是故意的 - 路由失败记录失败不影响主流程
            _x6_swallowed(__name__, e, "best-effort fallback")
        if self.trunk:
            try:
                self.trunk._log("模型熔断计数 %s=%d %s" %
                                (m, n, str(reason)[:60]))
            except Exception as e:  # 静默是故意的 - 日志失败不影响模型调用
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _mark_model_success(self, model):
        m = str(model)
        self._model_fail_counts[m] = 0
        self._model_cooldown.pop(m, None)

    def get_model_health(self, model=None):
        try:
            from core.usage_tracker import UsageTracker
            stats = UsageTracker(self.base).model_stats(model)
        except Exception:
            stats = {}
        if model:
            stats = dict(stats or {})
            stats["cooldown"] = max(
                0, round(float(self._model_cooldown.get(str(model), 0)) - time.time(), 1))
            return stats
        for name in list(self._model_cooldown):
            if name in stats:
                stats[name]["cooldown"] = max(
                    0, round(float(self._model_cooldown[name]) - time.time(), 1))
        return stats

    def _touch(self):
        """记录调用时间"""
        self._last_call = time.time()
        self._unloaded = False  # 重新加载了

    def reset_fail_count(self):
        """重置失败计数"""
        self._fail_count = 0
        return {"成功": True}
