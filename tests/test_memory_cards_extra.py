# -*- coding: utf-8 -*-
"""记忆卡：触发规则、规则提取、LLM 提取、去重、检索和分类。"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import modules.installed.memory_cards as mc  # noqa: E402
from modules.installed.memory_cards import MemoryCards  # noqa: E402


class _LLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, _messages):
        return self.reply


class _Trunk:
    def __init__(self, base):
        self.base = str(base)
        self.modules = {}
        self._logs = []

    def rule(self, _key, default):
        return default

    def _log(self, msg):
        self._logs.append(msg)


def _cards(tmp_path, monkeypatch, llm=None):
    path = tmp_path / "data" / "memory_cards.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mc, "CARDS_PATH", str(path))
    trunk = _Trunk(tmp_path)
    if llm is not None:
        trunk.modules["llm"] = llm
    return MemoryCards(trunk), path


def test_memory_trigger_rules(tmp_path, monkeypatch):
    m, _ = _cards(tmp_path, monkeypatch)
    m.rounds = 0
    assert m._should_trigger("普通") == "轮数"
    m.rounds = 1
    assert m._should_trigger("我喜欢 Python") == "强信号"
    assert m._should_trigger("今天很难过") == "情绪"
    m._last_text = "Python 项目"
    assert m._should_trigger("今天买猫") == "话题切换"


def test_rule_cards_and_classification(tmp_path, monkeypatch):
    m, _ = _cards(tmp_path, monkeypatch)
    assert "计划:" in m._rule_card("我想去学 Python", "强信号")["facts"][0]
    assert "偏好:" in m._rule_card("我喜欢咖啡", "强信号")["facts"][0]
    assert "事实:" in m._rule_card("我买了新车", "强信号")["facts"][0]
    assert "情感:" in m._rule_card("今天很开心", "情绪")["facts"][0]
    assert m.classify_card(["工作项目代码"]) == "工作"
    assert m.classify_card(["吃饭睡觉游戏"]) == "生活"
    assert m.classify_card(["朋友聚会"]) == "朋友"
    assert m.classify_card(["其他内容"]) == "其他"


def test_llm_card_and_summarize_dedup(tmp_path, monkeypatch):
    llm = _LLM('{"facts":["偏好:喜欢Python"],"feelings":"开心","follow_up":"问问项目"}')
    m, path = _cards(tmp_path, monkeypatch, llm=llm)
    m.rounds = 1
    card = m._llm_card("我喜欢 Python", "好的", "强信号")
    assert card["facts"][0].startswith("偏好")
    r1 = m.maybe_summarize("我喜欢 Python", "好的")
    assert r1["触发"] is True
    assert path.exists()
    r2 = m.maybe_summarize("我喜欢 Python", "好的")
    assert r2.get("重复") is True


def test_hint_search_recall_importance(tmp_path, monkeypatch):
    m, path = _cards(tmp_path, monkeypatch)
    now = __import__("time").time()
    rows = [
        {"date": "2026-10-20", "facts": ["偏好:喜欢咖啡"], "time": now,
         "follow_up": "问咖啡"},
        {"date": "2026-10-20", "facts": ["朋友张三最近搬家"], "time": now},
    ]
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
                    encoding="utf-8")
    assert "小6记得这些事" in m.hint()
    assert m._dup_with_history("偏好:喜欢咖啡") is False
    m._hint_history = ["偏好:喜欢咖啡"]
    assert m._dup_with_history("偏好:喜欢咖啡") is True
    assert m.search_cards("咖啡")["找到"] == 1
    assert m.recall_related("张三")["相关记忆"]
    card = {}
    assert m.set_importance(card, 5)["重要性"] == 5
    assert m.stats()["记忆卡总数"] == 2