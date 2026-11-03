# -*- coding: utf-8 -*-
"""分渠道上下文预算（第 2 批深度③）的离线测试。

要点：
* 系统/人格消息永不裁；
* 最后一条 user 永不裁（模型没有当前问题就答不了）；
* 历史/检索/工具各自有配额，超长的检索片段不能把历史挤空。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.context_budget import (  # noqa: E402
    DEFAULT_SHARES, channel_budgets, channel_of, estimate_tokens,
    trim_by_channel, trim_messages)


def test_channel_of_classifies_messages():
    assert channel_of({"role": "user", "content": "今天好累"}) == "history"
    assert channel_of({"role": "system", "content": "你是小6，住在用户电脑里"}) == "persona"
    assert channel_of({"role": "system", "content": "以下是相关知识：..."}) == "rag"
    assert channel_of({"role": "system", "content": "可用工具：fs_edit"}) == "tools"
    assert channel_of({"role": "tool", "content": "ok"}) == "tools"
    assert channel_of({"role": "system", "content": "禁止编造"}) == "system"
    assert channel_of("不是 dict") == "history"


def test_channel_budgets_split_and_only_accept_valid_shares():
    budgets = channel_budgets(10000)
    assert set(budgets) == set(DEFAULT_SHARES)
    assert budgets["history"] == int(10000 * DEFAULT_SHARES["history"])
    # 用户只覆盖一路 → 其余按默认（总权重归一后仍然合计 ≈ 总预算）
    custom = channel_budgets(10000, {"history": 0.8})
    assert custom["history"] > budgets["history"]
    assert sum(custom.values()) <= 10100
    # 非法值忽略，不能把预算算成 0
    broken = channel_budgets(10000, {"history": "很長", "rag": -1})
    assert broken["history"] > 0 and broken["rag"] > 0


def test_trim_keeps_system_and_last_user():
    msgs = [{"role": "system", "content": "你是小6，" + "S" * 400}]
    for i in range(20):
        msgs.append({"role": "user", "content": "第%d轮 " % i + "x" * 400})
        msgs.append({"role": "assistant", "content": "答%d " % i + "y" * 400})
    out = trim_by_channel(msgs, max_tokens=1200, reserve=200)
    assert out[0]["role"] == "system"
    # 顺序保持原样，所以最后一条是「第19轮的回答」，但最新的用户问题必须在
    text = "\n".join(str(m.get("content")) for m in out)
    assert "第19轮" in text, "最新的用户问题必须保留"
    assert len(out) < len(msgs)
    # 被裁掉的早期对话不白丢：压成一条摘要留在上下文里
    from core.context_budget import SUMMARY_PREFIX
    assert any(SUMMARY_PREFIX in str(m.get("content")) for m in out)


def test_roll_up_compresses_early_turns_within_budget():
    from core.context_budget import SUMMARY_PREFIX, roll_up
    early = [{"role": "user", "content": "我每天早上喝一杯美式咖啡。"},
             {"role": "assistant", "content": "记下了。"},
             {"role": "user", "content": "我六点下班。很多很多废话" + "x" * 400}]
    summary = roll_up(early, max_tokens=60)
    assert summary["role"] == "system"
    assert SUMMARY_PREFIX in summary["content"]
    assert "美式咖啡" in summary["content"], "关键事实要被带进摘要"
    assert estimate_tokens(summary) <= 60, "摘要也要守 token 上限"
    assert roll_up([]) is None


def test_trim_drops_oversized_rag_before_history():
    """超长检索片段不能把最近对话挤掉（这是原来单一总预算的毛病）。"""
    msgs = [
        {"role": "system", "content": "你是小6"},
        {"role": "system", "content": "以下是相关知识：" + "R" * 8000},
        {"role": "user", "content": "我早上喝什么？"},
        {"role": "assistant", "content": "美式咖啡"},
        {"role": "user", "content": "那我几点上班？"},
    ]
    out = trim_by_channel(msgs, max_tokens=2000, reserve=200)
    text = "\n".join(str(m.get("content")) for m in out)
    assert "美式咖啡" in text, "最近对话不能被检索片段挤掉"
    assert "那我几点上班？" in text
    # RAG 被配额限制住，不再吃掉全部预算
    assert len(out) < len(msgs)


def test_twenty_round_conversation_keeps_early_fact():
    """验收项：20 轮长对话不丢前文（预算是够的，就不该裁掉第一轮）。"""
    msgs = [{"role": "system", "content": "你是小6"},
            {"role": "user", "content": "我每天早上喝一杯美式咖啡。"},
            {"role": "assistant", "content": "记下了"}]
    for i in range(19):
        msgs.append({"role": "user", "content": "第%d轮闲聊" % i})
        msgs.append({"role": "assistant", "content": "嗯嗯"})
    out = trim_messages(msgs, max_tokens=6000, reserve=800)
    text = "\n".join(str(m.get("content")) for m in out)
    assert "美式咖啡" in text, "预算够用时不能把 20 轮前的事实裁掉"


def test_trim_noop_when_within_budget_and_backward_compatible():
    small = [{"role": "system", "content": "你是小6"},
             {"role": "user", "content": "你好"}]
    assert trim_messages(small, max_tokens=6000, reserve=800) == small
    assert estimate_tokens(small) > 0
    # 老写法（位置参数）仍然可用
    assert trim_messages(small, 800, 200) == small
