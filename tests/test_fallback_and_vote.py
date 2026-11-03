# -*- coding: utf-8 -*-
"""B5：自动 / 兜底组（local_fallback / model_vote / group_debate）

守住四件事
----------
1. **兜底模块自己不能成为故障源**：LLM 报错/超时/接口对不上，
   规则兜底必须照样返回一句人话，不许抛异常。
2. 分级真的分开了（问候 / 低落 / 提问 …），不能所有输入都回同一句。
3. ``model_vote`` 的部分可用也要出结果：一个模型超时不能把全票作废。
4. ``group_debate`` 的轮次与超时必须有上限，收不齐要降级继续。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))


class _T:
    def __init__(self, config=None, modules=None):
        self.base = "."
        self.config = config or {}
        self.modules = modules or {}


class _FakeLLM:
    """按模型名给不同答案；可选慢速/报错，用来验超时与降级"""

    def __init__(self, mapping=None, sleep=0.0, raises=False, default="回答"):
        self.mapping = mapping or {}
        self.sleep = sleep
        self.raises = raises
        self.default = default
        self.calls = []

    def chat(self, message, inject_persona=True, force_model=None):
        self.calls.append((message, force_model))
        if self.sleep:
            time.sleep(self.sleep)
        if self.raises:
            raise RuntimeError("模型挂了")
        if force_model and force_model in self.mapping:
            return self.mapping[force_model]
        return self.default


class _OldLLM:
    """只收 message 的老接口（真实 LLMClient 的历史形状）"""

    def chat(self, message):
        return "老接口回复"


# ══════════════════════════════════════════════════════════════
# local_fallback
# ══════════════════════════════════════════════════════════════
def _fallback(config=None, modules=None):
    from core.local_fallback import LocalFallback
    return LocalFallback(_T(config=config, modules=modules))


def test_fallback_classify_separates_intents():
    fb = _fallback()
    assert fb.classify("") == "empty"
    assert fb.classify("   ") == "empty"
    assert fb.classify("你好呀") == "greeting"
    assert fb.classify("谢谢你") == "thanks"
    assert fb.classify("今天真的好累，有点崩溃") == "low"
    assert fb.classify("这个怎么设置？") == "help"
    # 什么都没匹配上才是兜底，不能默认全走 low/help
    assert fb.classify("今天天气不错") == "fallback"


def test_fallback_empty_and_low_replies_differ():
    fb = _fallback()
    assert fb.reply("") == "你好，我在。"
    low = fb.reply("我最近压力很大")
    assert "我在" in low, low
    assert low != fb.reply("你好")


def test_fallback_uses_rules_when_no_llm():
    fb = _fallback()
    assert fb.reply("谢谢你") == "不客气～能帮上就好。"
    # 没配 fallback_model 就完全不碰模型：rules 断言成立即说明没走模型分支
    r = fb.answer("再见")
    assert r["分级"] == "bye"
    assert isinstance(r["回复"], str) and r["回复"]


def test_fallback_uses_small_model_when_configured():
    llm = _FakeLLM(default="模型回复了一句人话")
    fb = _fallback(config={"fallback_model": "qwen2.5:1.5b"},
                   modules={"llm": llm})
    got = fb.reply("今天天气不错")
    assert got == "模型回复了一句人话"
    assert llm.calls and llm.calls[0][1] == "qwen2.5:1.5b", llm.calls


def test_fallback_falls_back_to_rules_when_model_dies():
    """模型报错必须退回规则，不许把异常抛给聊天主流程"""
    for llm in (_FakeLLM(raises=True), _OldLLM()):
        fb = _fallback(config={"fallback_model": "x"}, modules={"llm": llm})
        got = fb.reply("今天天气不错")
        assert isinstance(got, str) and got
        assert "没连上" in got or "老接口" in got, got


def test_fallback_model_never_used_for_empty():
    llm = _FakeLLM(default="不该被调用")
    fb = _fallback(config={"fallback_model": "x"}, modules={"llm": llm})
    assert fb.reply("") == "你好，我在。"
    assert not llm.calls


def test_fallback_run_reports_levels():
    r = _fallback().run()
    assert r["状态"]
    assert "fallback" in r["分级"] and "greeting" in r["分级"]


# ══════════════════════════════════════════════════════════════
# model_vote
# ══════════════════════════════════════════════════════════════
def _vote(modules=None):
    from core.model_vote import ModelVote
    return ModelVote(_T(modules=modules))


def test_vote_rejects_empty_and_missing_llm():
    v = _vote()
    assert v.chat_vote("  ").get("ok") is False
    r = v.chat_vote("问题")
    assert r.get("ok") is False
    assert "LLM" in str(r.get("error"))


def test_vote_majority_picks_common_answer():
    llm = _FakeLLM(mapping={"a": "可以", "b": "可以", "c": "不可以"})
    r = _vote({"llm": llm}).chat_vote("问题", models=["a", "b", "c"],
                                      strategy="majority")
    assert r["ok"] is True
    assert r["final"] == "可以", r
    assert r["模型数"] == 3
    # 顺序稳定：按请求顺序返回
    assert [x["model"] for x in r["answers"]] == ["a", "b", "c"]


def test_vote_longest_strategy():
    llm = _FakeLLM(mapping={"a": "短", "b": "这是一段明显更长的回答内容"})
    r = _vote({"llm": llm}).chat_vote("问题", models=["a", "b"],
                                     strategy="longest")
    assert r["final"] == "这是一段明显更长的回答内容"


def test_vote_partial_failure_still_returns_answer():
    llm = _FakeLLM(mapping={"a": "好的"}, default="")
    llm.mapping["bad"] = ""
    v = _vote({"llm": llm})
    r = v.chat_vote("问题", models=["a", "bad"], strategy="judge")
    assert r["ok"] is True, r
    assert r["final"] == "好的"
    assert "降级" in r or any(x["状态"] != "ok" for x in r["answers"])


def test_vote_all_failed_reports_reason():
    llm = _FakeLLM(default="")
    r = _vote({"llm": llm}).chat_vote("问题", models=["a", "b"], strategy="judge")
    assert r["ok"] is False
    assert "没用" in str(r["error"]) or "没给出" in str(r["error"])


def test_vote_timeout_marks_pending_and_keeps_others():
    """慢模型超时不能把整场投票卡死：到点就标 超时 返回"""
    slow = _FakeLLM(mapping={"slow": "慢的答案"}, sleep=1.5)
    fast = _FakeLLM(mapping={"fast": "快的答案"})

    class _TwoLLM:
        def __init__(self):
            self.calls = []

        def chat(self, message, inject_persona=True, force_model=None):
            if force_model == "slow":
                return slow.chat(message, force_model=force_model)
            return fast.chat(message, force_model=force_model)

    r = _vote({"llm": _TwoLLM()}).chat_vote("问题", models=["slow", "fast"],
                                            strategy="judge", timeout=1)
    assert r["ok"] is True, r
    states = {x["model"]: x["状态"] for x in r["answers"]}
    assert states.get("slow") == "超时", states
    assert states.get("fast") == "ok", states
    assert r["final"] == "快的答案"


def test_vote_model_list_normalisation():
    from core.model_vote import MAX_MODELS, ModelVote
    models = ModelVote._norm_models(" a ，b , a , ,c")
    assert models == ["a", "b", "c"], models
    assert len(ModelVote._norm_models(["m%d" % i for i in range(20)])) \
        == MAX_MODELS
    assert ModelVote._norm_timeout("坏值") == 20.0
    assert ModelVote._norm_timeout(0) == 1.0


def test_vote_accepts_old_message_only_llm():
    r = _vote({"llm": _OldLLM()}).chat_vote("问题", models=["x"], strategy="judge")
    assert r["ok"] is True and r["final"] == "老接口回复"


# ══════════════════════════════════════════════════════════════
# group_debate
# ══════════════════════════════════════════════════════════════
def _debate(modules=None):
    from core.group_debate import GroupDebate
    return GroupDebate(_T(modules=modules))


def test_debate_rejects_empty_topic_and_missing_llm():
    d = _debate()
    assert d.debate("   ")["ok"] is False
    assert d.debate("要不要换工作")["ok"] is False


def test_debate_rounds_are_clamped():
    from core.group_debate import MAX_ROUNDS, GroupDebate
    assert GroupDebate._norm_rounds(99) == MAX_ROUNDS
    assert GroupDebate._norm_rounds(0) == 1
    assert GroupDebate._norm_rounds("坏值") == 3


def test_debate_three_rounds_with_consensus():
    llm = _FakeLLM(default="我觉得可以")
    d = _debate({"llm": llm})
    r = d.debate("要不要换工作", rounds=3)
    assert r["ok"] is True
    assert [x["round"] for x in r["rounds"]] == [1, 2, 3]
    assert r["rounds"][0]["answers"]["小七"]
    assert "共识" in r and r["共识"]
    assert r["总失败"] == 0


def test_debate_two_rounds_skips_consensus():
    llm = _FakeLLM(default="观点")
    r = _debate({"llm": llm}).debate("话题", rounds=2)
    assert [x["round"] for x in r["rounds"]] == [1, 2]
    assert "共识" not in r


def test_debate_all_models_dead_degrades_but_returns():
    llm = _FakeLLM(raises=True)
    r = _debate({"llm": llm}).debate("话题", rounds=3)
    assert r["ok"] is True, r
    assert r["总失败"] > 0
    assert "降级" in r
    assert "（无响应）" in r["rounds"][0]["answers"]["小七"]


def test_debate_single_ask_timeout():
    """共识那条是单条调用，卡住也要在 timeout 内回来"""
    from core.group_debate import GroupDebate
    d = GroupDebate(_T(modules={"llm": _FakeLLM(sleep=1.5)}))
    text, status = d._ask(d._llm(), "总结", "话题", timeout=1)
    assert status == "超时"
    assert "超时" in text


def test_debate_accepts_old_message_only_llm():
    r = _debate({"llm": _OldLLM()}).debate("话题", rounds=1, timeout=5)
    assert r["ok"] is True
    assert r["rounds"][0]["answers"]["小九"] == "老接口回复"


def test_debate_run_shape():
    r = _debate().run()
    assert len(r["角色"]) == 3
    assert r["轮次上限"] >= 3
