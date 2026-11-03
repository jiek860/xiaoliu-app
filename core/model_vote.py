# -*- coding: utf-8 -*-
"""v26-1.1: 多模型投票/融合（完整版）

策略
----
``longest`` 最长、``majority`` 多数相同、``judge`` 取第一个可用、
``merge`` 合并所有可用回答（取最长那版为主，附其余模型的一句话摘要）。

超时与降级（2026-11-02 补）
--------------------------
原来 ``ex.map`` 不带超时：一个模型卡住，整个投票就卡住（工具调用是
同步的，界面表现为"点了没反应"）。现在每个模型单独 ``submit``，
到点没收齐就取消剩下的，并把没收齐的标记成 ``超时`` ——
**部分可用**也要能出结果，不能因为一个慢模型把全票作废。
"""
import concurrent.futures
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_MODELS = ("glm-4-flash", "qwen-turbo", "deepseek-chat")
STRATEGIES = ("majority", "longest", "judge", "merge")
MAX_MODELS = 8
MAX_TIMEOUT = 120


class ModelVote:
    """多模型投票，自动选最优答案"""

    def __init__(self, trunk=None):
        self.trunk = trunk

    # ------------------------------------------------------------------
    @staticmethod
    def _norm_models(models):
        if not models:
            return list(DEFAULT_MODELS)
        if isinstance(models, str):
            models = [m.strip() for m in models.replace("，", ",").split(",")]
        out = []
        for m in models or []:
            text = str(m or "").strip()
            if text and text not in out:
                out.append(text)
        return out[:MAX_MODELS] or list(DEFAULT_MODELS)

    @staticmethod
    def _norm_timeout(timeout):
        try:
            value = float(timeout)
        except (TypeError, ValueError):
            return 20.0
        return max(1.0, min(MAX_TIMEOUT, value))

    def _one(self, llm, model, message):
        t0 = time.time()
        try:
            # 真实 LLMClient 的形参是 force_model；老接口/假 LLM 只收 message。
            # 逐级退让，别因为参数名不同就整票作废。
            try:
                ans = llm.chat(message, force_model=model)
            except TypeError:
                try:
                    ans = llm.chat(message, model=model)
                except TypeError:
                    ans = llm.chat(message)
        except Exception as e:
            _x6_swallowed(__name__, e, "model vote chat")
            return {"model": model, "answer": "错误: " + str(e)[:60],
                    "time": round(time.time() - t0, 2), "状态": "失败"}
        answer = str(ans or "").strip()
        if not answer:
            # 空回答不是「可用回答」：标失败，否则投票会把它当票投出去
            return {"model": model, "answer": "错误: 空回答",
                    "time": round(time.time() - t0, 2), "状态": "失败"}
        return {"model": model, "answer": answer[:2000],
                "time": round(time.time() - t0, 2), "状态": "ok"}

    # ------------------------------------------------------------------
    def chat_vote(self, message, models=None, strategy="judge", timeout=20):
        """多模型投票。

        ``timeout`` 是**整场**预算（秒），不是单模型 —— 工具调用有等待上限。
        """
        text = "" if message is None else str(message).strip()
        if not text:
            return {"ok": False, "error": "没给要问的问题（message 为空）",
                    "answers": [], "final": "", "strategy": strategy}
        if strategy not in STRATEGIES:
            strategy = "judge"
        models = self._norm_models(models)
        timeout = self._norm_timeout(timeout)

        llm = (getattr(self.trunk, "modules", None) or {}).get("llm") \
            if self.trunk is not None else None
        if not llm or not hasattr(llm, "chat"):
            return {"ok": False, "error": "LLM未加载", "answers": [],
                    "final": "LLM未加载", "strategy": strategy}

        results = []
        started = time.time()
        # ⚠️ 不能用 ``with ThreadPoolExecutor(...)``：__exit__ 会 shutdown(wait=True)，
        # 等于把「超时」又变回「一直等慢模型」。手动 shutdown(wait=False)，
        # 没回来的那条留给后台线程自己结束。
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(models))
        try:
            futures = {ex.submit(self._one, llm, m, text): m for m in models}
            done, pending = concurrent.futures.wait(
                futures, timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETED)
            for fut in done:
                try:
                    results.append(fut.result())
                except Exception as e:
                    _x6_swallowed(__name__, e, "model vote collect")
                    results.append({"model": futures[fut],
                                    "answer": "错误: " + str(e)[:60],
                                    "time": 0, "状态": "失败"})
            for fut in pending:
                fut.cancel()
                results.append({"model": futures[fut],
                                "answer": "错误: 超时未返回", "time": timeout,
                                "状态": "超时"})
        finally:
            ex.shutdown(wait=False)

        # 顺序稳定：按请求的模型顺序排，日志/界面不会每次乱跳
        order = {m: i for i, m in enumerate(models)}
        results.sort(key=lambda r: order.get(r.get("model"), 999))
        final = self._pick_final(results, strategy)
        ok = any(r.get("状态") == "ok" for r in results)
        r = {
            "ok": ok,
            "answers": results,
            "final": final,
            "strategy": strategy,
            "耗时": round(time.time() - started, 2),
            "模型数": len(models),
        }
        bad = [x for x in results if x.get("状态") != "ok"]
        if bad:
            r["降级"] = "、".join("%s %s" % (x["model"], x["状态"]) for x in bad)
        if not ok:
            r["error"] = "所有模型都没给出可用回答（超时 %.0f 秒）" % timeout
        return r

    # ------------------------------------------------------------------
    def _pick_final(self, results, strategy):
        """按策略选最终答案；没有可用回答时给出空串 + 原因在 error 里"""
        valid = [r for r in results
                 if r.get("状态") == "ok" and str(r.get("answer") or "").strip()]
        if not valid:
            return ""

        if strategy == "longest":
            return max(valid, key=lambda r: len(r["answer"]))["answer"]

        if strategy == "majority":
            from collections import Counter
            keys = [r["answer"][:200] for r in valid]
            most = Counter(keys).most_common(1)
            if most:
                for r in valid:
                    if r["answer"][:200] == most[0][0]:
                        return r["answer"]
            return valid[0]["answer"]

        if strategy == "merge":
            base = max(valid, key=lambda r: len(r["answer"]))
            others = ["【%s】%s" % (r["model"], r["answer"][:80])
                      for r in valid if r is not base][:3]
            if not others:
                return base["answer"]
            return base["answer"] + "\n\n其他模型观点：\n" + "\n".join(others)

        # judge：第一个可用回答（没有额外裁判模型，避免再多一次调用）
        return valid[0]["answer"]

    def run(self, *a):
        return {"功能": "多模型投票", "策略": list(STRATEGIES),
                "说明": "每个模型单独超时，收不齐就降级出结果"}
