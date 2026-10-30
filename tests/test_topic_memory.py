# -*- coding: utf-8 -*-
"""批次 D11：短期话题摘要 + 长期记忆（向量检索）注入。"""
import os

from core.pipeline.context_builder import ContextBuilder
from core.pipeline.prompt_assembler import PromptAssembler


class FakeTrunk:
    def __init__(self, base=".", pairs=None, rules=None):
        self.base = str(base)
        self.config = {}
        self.rules = rules or {}
        self.modules = {}
        self.current_user = "default"
        self.memory = {"default": list(pairs or [])}
        self._active_skill_prompt = ""
        self.loaded = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def mem_recent(self, n=6):
        return ((self.memory or {}).get("default") or [])[-n:]

    def _load_lazy(self, name):
        self.loaded.append(name)

    def _log(self, msg):
        return None


def _pairs(n):
    return [{"u": "第%d个话题" % i, "a": "回复%d" % i} for i in range(n)]


def _topic_messages(messages):
    return [m["content"] for m in messages
            if m["role"] == "system" and m["content"].startswith("近期话题：")]


def test_short_conversation_has_no_topic_hint():
    trunk = FakeTrunk(pairs=_pairs(10), rules={"聊天.人格卡": "off"})
    messages = PromptAssembler(trunk).assemble("接着说", "", False)
    assert _topic_messages(messages) == []


def test_long_conversation_injects_topic_summary():
    trunk = FakeTrunk(pairs=_pairs(20), rules={"聊天.人格卡": "off"})
    hints = _topic_messages(PromptAssembler(trunk).assemble("接着说", "", False))
    assert len(hints) == 1
    # 话题清单是 "话题(次数) · ..." 的形式，且长度受控
    assert "(" in hints[0] and len(hints[0]) <= 410
    # 不能塞进用户输入：最后一条仍是用户原话
    messages = PromptAssembler(trunk).assemble("接着说", "", False)
    assert messages[-1] == {"role": "user", "content": "接着说"}


def test_simple_input_skips_topic_hint():
    trunk = FakeTrunk(pairs=_pairs(30), rules={"聊天.人格卡": "off"})
    messages = PromptAssembler(trunk).assemble("在吗", "", True)
    assert _topic_messages(messages) == []


def test_topic_hint_tolerates_broken_memory():
    trunk = FakeTrunk(pairs=_pairs(30), rules={"聊天.人格卡": "off"})
    trunk.memory = None   # 脏数据：读不到就不注入，别让回复挂掉
    assert _topic_messages(PromptAssembler(trunk).assemble("x", "", False)) == []


class _Vs:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, top_k=5):
        return self.hits[:top_k]


def test_ctx_vector_lazy_loads_when_db_exists(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "data"), exist_ok=True)
    open(os.path.join(str(tmp_path), "data", "vectors.db"), "w").close()
    trunk = FakeTrunk(base=tmp_path)
    # 懒加载时装进 modules，模拟真实 trunk 行为
    def _load(name):
        trunk.modules["vector_store"] = _Vs([{"text": "用户上次说喜欢简洁", "score": 0.9}])
    trunk._load_lazy = _load
    text = ContextBuilder(trunk)._ctx_vector("还记得吗")
    assert "用户上次说喜欢简洁" in text


def test_ctx_vector_cold_start_without_db(tmp_path):
    trunk = FakeTrunk(base=tmp_path)
    assert ContextBuilder(trunk)._ctx_vector("随便问问") == ""
    assert trunk.loaded == []


def test_ctx_vector_hit_goes_into_context(tmp_path):
    trunk = FakeTrunk(base=tmp_path)
    trunk.modules["vector_store"] = _Vs([{"text": "偏好：回答要短", "score": 0.8}])
    ctx = ContextBuilder(trunk).build("帮我写个总结", is_simple=False)
    assert "偏好：回答要短" in ctx
