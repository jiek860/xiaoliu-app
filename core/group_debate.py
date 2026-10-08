# -*- coding: utf-8 -*-
"""v26-2.2: 多智能体辩论 完整版"""
import concurrent.futures


class GroupDebate:
    """多角色辩论：观点→反驳→共识"""
    def __init__(self, trunk=None):
        self.trunk = trunk

    def debate(self, topic, rounds=3):
        llm = self.trunk.modules.get("llm") if self.trunk else None
        if not llm:
            return {"错误": "LLM未加载"}

        roles = ["小七", "小八", "小九"]
        personas = {
            "小七": "你是小七，理性务实，注重实际效果",
            "小八": "你是小八，乐观创新，喜欢尝试新事物",
            "小九": "你是小九，谨慎保守，注重风险和成本",
        }
        history = {"topic": topic, "rounds": []}

        # 第1轮：独立观点
        r1 = {}
        def _r1(role):
            prompt = "话题：%s\n请从你的角度发表观点（不超过150字）：" % topic
            try:
                ans = llm.chat(prompt)
                return role, str(ans)[:200]
            except Exception:
                return role, "（无响应）"
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            for role, ans in ex.map(_r1, roles):
                r1[role] = ans
        history["rounds"].append({"round": 1, "type": "观点", "answers": r1})

        # 第2轮：互相反驳（如果rounds>=2）
        if rounds >= 2:
            r2 = {}
            def _r2(role):
                others = "\n".join("%s: %s" % (r, r1[r][:100]) for r in roles if r != role)
                prompt = "话题：%s\n其他人观点：\n%s\n请反驳或补充（不超过150字）：" % (topic, others)
                try:
                    ans = llm.chat(prompt)
                    return role, str(ans)[:200]
                except Exception:
                    return role, "（无响应）"
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                for role, ans in ex.map(_r2, roles):
                    r2[role] = ans
            history["rounds"].append({"round": 2, "type": "反驳", "answers": r2})

        # 第3轮：共识总结
        if rounds >= 3:
            all_views = "\n".join("%s: %s" % (r, r1[r][:100]) for r in roles)
            prompt = "话题：%s\n各角色观点：\n%s\n请总结共识，给出最终结论（不超过200字）：" % (topic, all_views)
            try:
                consensus = llm.chat(prompt)
            except Exception:
                consensus = "（无法达成共识）"
            history["rounds"].append({"round": 3, "type": "共识", "consensus": str(consensus)[:300]})

        history["ok"] = True
        return history

    def run(self, *a):
        return {"功能": "多智能体辩论", "角色": ["小七", "小八", "小九"]}
