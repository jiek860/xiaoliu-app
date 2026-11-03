# -*- coding: utf-8 -*-
"""v26-2.2: 多智能体辩论（完整版）

角色：小七（理性务实）/ 小八（乐观创新）/ 小九（谨慎保守）。
流程：第 1 轮各说观点 → 第 2 轮互相反驳 → 第 3 轮总结共识。

轮次上限与超时（2026-11-02 补）
------------------------------
原来 ``rounds`` 不做校验、也没有超时：``rounds=99`` 会真跑几十轮，
一个模型卡住就整场挂住。现在：

* ``rounds`` 夹到 1..5；
* 每轮给一个**整轮预算**（``timeout`` 秒，默认 30），到点把没回来的
  标成 ``超时`` 继续下一轮 —— 少一条发言不该让整场作废；
* 返回里带 ``失败`` 计数与 ``降级`` 说明，界面/日志能看出这场的完整性。
"""
import concurrent.futures
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

ROLES = ("小七", "小八", "小九")
PERSONAS = {
    "小七": "你是小七，理性务实，注重实际效果",
    "小八": "你是小八，乐观创新，喜欢尝试新事物",
    "小九": "你是小九，谨慎保守，注重风险和成本",
}
MAX_ROUNDS = 5
MAX_TIMEOUT = 120


class GroupDebate:
    """多角色辩论：观点 → 反驳 → 共识"""

    def __init__(self, trunk=None):
        self.trunk = trunk

    # ------------------------------------------------------------------
    @staticmethod
    def _norm_rounds(rounds):
        try:
            value = int(rounds)
        except (TypeError, ValueError):
            return 3
        return max(1, min(MAX_ROUNDS, value))

    @staticmethod
    def _norm_timeout(timeout):
        try:
            value = float(timeout)
        except (TypeError, ValueError):
            return 30.0
        return max(2.0, min(MAX_TIMEOUT, value))

    def _llm(self):
        if self.trunk is None:
            return None
        return (getattr(self.trunk, "modules", None) or {}).get("llm")

    def _ask(self, llm, role, prompt, timeout=None):
        """让某个角色发言；返回 (文本, 状态)。异常一律变成可读占位。

        ``timeout`` 只给「共识」这种单条调用用 —— 三条并行发言的超时在
        :meth:`_round` 里统一管，单条卡住不该让整场挂住。
        """
        def _call():
            try:
                try:
                    ans = llm.chat(prompt, inject_persona=False)
                except TypeError:
                    ans = llm.chat(prompt)
            except Exception as e:
                _x6_swallowed(__name__, e, "debate ask")
                return "（无响应）", "失败"
            answer = str(ans or "").strip()
            return (answer[:300], "ok") if answer else ("（无响应）", "失败")

        if not timeout:
            return _call()
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(_call)
            try:
                return fut.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                return "（超时）", "超时"
            except Exception as e:
                _x6_swallowed(__name__, e, "debate ask collect")
                return "（无响应）", "失败"
        finally:
            ex.shutdown(wait=False)

    def _round(self, llm, prompt_fn, timeout):
        """并行让三个角色发言，返回 (answers, 失败数)

        ⚠️ 这里**不能**用 ``with ThreadPoolExecutor(...)``：它的 ``__exit__``
        会 ``shutdown(wait=True)``，等于把「超时」重新变成「一直等」。
        手动 shutdown(wait=False)，慢模型留给后台线程自己跑完。
        """
        answers, failures = {}, 0
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=len(ROLES))
        try:
            futures = {ex.submit(self._ask, llm, role, prompt_fn(role)):
                       role for role in ROLES}
            done, pending = concurrent.futures.wait(
                futures, timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETED)
            for fut in done:
                try:
                    answers[futures[fut]] = fut.result()
                except Exception as e:
                    _x6_swallowed(__name__, e, "debate collect")
                    answers[futures[fut]] = ("（无响应）", "失败")
            for fut in pending:
                fut.cancel()
                answers[futures[fut]] = ("（超时）", "超时")
        finally:
            ex.shutdown(wait=False)
        for role in ROLES:
            text, status = answers.get(role, ("（无响应）", "失败"))
            answers[role] = text
            if status != "ok":
                failures += 1
        return answers, failures

    # ------------------------------------------------------------------
    def debate(self, topic, rounds=3, timeout=30):
        text = "" if topic is None else str(topic).strip()
        if not text:
            return {"ok": False, "错误": "没给辩题（topic 为空）",
                    "topic": "", "rounds": []}
        rounds = self._norm_rounds(rounds)
        timeout = self._norm_timeout(timeout)
        llm = self._llm()
        if not llm or not hasattr(llm, "chat"):
            return {"ok": False, "错误": "LLM未加载", "topic": text, "rounds": []}

        started = time.time()
        history = {"topic": text, "rounds": [], "总失败": 0,
                   "轮次上限": MAX_ROUNDS}
        r1 = {}

        def _p1(role):
            return ("%s\n话题：%s\n请从你的角度发表观点（不超过150字）："
                    % (PERSONAS.get(role, ""), text))

        r1, failed = self._round(llm, _p1, timeout)
        history["总失败"] += failed
        history["rounds"].append({"round": 1, "type": "观点", "answers": r1,
                                  "失败": failed})

        if rounds >= 2:
            def _p2(role):
                others = "\n".join("%s: %s" % (r, str(r1.get(r, ""))[:100])
                                   for r in ROLES if r != role)
                return ("%s\n话题：%s\n其他人观点：\n%s\n"
                        "请反驳或补充（不超过150字）："
                        % (PERSONAS.get(role, ""), text, others))

            r2, failed = self._round(llm, _p2, timeout)
            history["总失败"] += failed
            history["rounds"].append({"round": 2, "type": "反驳",
                                      "answers": r2, "失败": failed})

        if rounds >= 3:
            all_views = "\n".join("%s: %s" % (r, str(r1.get(r, ""))[:100])
                                  for r in ROLES)
            prompt = ("话题：%s\n各角色观点：\n%s\n"
                      "请总结共识，给出最终结论（不超过200字）："
                      % (text, all_views))
            consensus, status = self._ask(llm, "总结", prompt, timeout * 2)
            if status != "ok":
                history["总失败"] += 1
            history["rounds"].append({"round": 3, "type": "共识",
                                      "consensus": consensus[:300],
                                      "状态": status})
            history["共识"] = consensus[:300]

        history["ok"] = True
        history["耗时"] = round(time.time() - started, 2)
        if history["总失败"]:
            history["降级"] = ("有 %d 条发言超时/失败（已用占位继续），"
                               "结论可能不完整" % history["总失败"])
        return history

    def run(self, *a):
        return {"功能": "多智能体辩论", "角色": list(ROLES),
                "轮次上限": MAX_ROUNDS,
                "说明": "rounds 1..5；每轮有时间预算，收不齐就降级继续"}
