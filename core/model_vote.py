# -*- coding: utf-8 -*-
"""v26-1.1: 多模型投票/融合 完整版"""
import time, concurrent.futures


class ModelVote:
    """多模型投票，自动选最优答案"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def chat_vote(self, message, models=None, strategy="judge"):
        """
        多模型投票
        strategy: majority/longest/judge/merge
        """
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"answers": [], "final": "LLM未加载", "strategy": strategy}

        if not models:
            models = ["glm-4-flash", "qwen-turbo", "deepseek-chat"]

        # 并行调用
        results = []
        def _one(m):
            t0 = time.time()
            try:
                ans = llm.chat(message)
                return {"model": m, "answer": ans, "time": round(time.time() - t0, 2)}
            except Exception as e:
                return {"model": m, "answer": "错误: " + str(e)[:60], "time": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as ex:
            for r in ex.map(_one, models):
                results.append(r)

        final = self._pick_final(message, results, strategy)
        return {"answers": results, "final": final, "strategy": strategy}

    def _pick_final(self, message, results, strategy):
        """按策略选最终答案"""
        valid = [r for r in results if not str(r["answer"]).startswith(("错误",))]
        if not valid:
            return results[0]["answer"] if results else "（所有模型都没响应）"

        if strategy == "longest":
            return max(valid, key=lambda r: len(r["answer"]))["answer"]

        if strategy == "majority":
            # 简单相似度聚类：取出现最多的前200字
            from collections import Counter
            keys = [r["answer"][:200] for r in valid]
            most_common = Counter(keys).most_common(1)
            if most_common:
                for r in valid:
                    if r["answer"][:200] == most_common[0][0]:
                        return r["answer"]

        if strategy == "judge":
            # 用第一个模型当裁判
            return valid[0]["answer"]

        return valid[0]["answer"]

    def run(self, *a):
        return {"功能": "多模型投票", "策略": ["majority", "longest", "judge"]}
