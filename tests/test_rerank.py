# -*- coding: utf-8 -*-
"""第 4 批 A2 / 深度④⑤：三路知识重排（rerank）+ "相关知识：① …（来源：…）"。

这些用例只验证**确定性的重排/排版**：不打模型、不联网、不碰 Qt。
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.pipeline import rerank as rr  # noqa: E402
from core.pipeline.context_builder import ContextBuilder  # noqa: E402

NOW = time.time()


class _Vs:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, top_k=5):
        return self.hits[:top_k]


class _Ml:
    def recall(self, query, top_k=2, hours=48):
        return [{"type": "情景", "scene": "编程",
                 "time": "2026-10-29 10:00", "text": "用户上次在改登录页"}]


class _Kg:
    def rag_query(self, query):
        return "登录页依赖 auth 模块"


class FakeTrunk:
    def __init__(self, base=".", modules=None, rules=None):
        self.base = str(base)
        self.config = {}
        self.modules = modules or {}
        self.rules = rules or {}
        self.logs = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _load_lazy(self, name):
        return None

    def _log(self, msg):
        self.logs.append(str(msg))


def _write_card(base, text):
    folder = os.path.join(str(base), "data")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "memory_cards.jsonl"), "a",
              encoding="utf-8") as fp:
        fp.write(json.dumps({"facts": [text], "time": NOW},
                            ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- dedupe

def test_dedupe_merges_same_text_and_keeps_sources():
    items = [{"text": "用户喜欢简洁的回答方式", "source": "记忆", "score": 0.4},
             {"text": "用户喜欢简洁的回答方式！！", "source": "知识库",
              "score": 0.9}]
    kept = rr.dedupe(items)
    assert len(kept) == 1
    assert kept[0]["score"] == 0.9                  # 分数取高
    assert "记忆" in kept[0]["source"]
    assert "知识库" in kept[0]["source"]            # 来源合并，不丢


def test_dedupe_keeps_different_text():
    items = [{"text": "用户喜欢简洁的回答", "source": "记忆"},
             {"text": "项目用 PyQt5 做界面", "source": "知识库"}]
    assert len(rr.dedupe(items)) == 2


# ---------------------------------------------------------------- MMR

def test_mmr_prefers_diverse_item_over_near_duplicate():
    items = [{"text": "苹果手机电池续航", "relevance": 0.90},
             {"text": "苹果手机电池续航时间", "relevance": 0.88},
             {"text": "安卓手机系统更新", "relevance": 0.60}]
    picked = rr.mmr(items, top_k=2, lambda_=0.7)
    assert len(picked) == 2
    assert picked[0]["text"] == "苹果手机电池续航"
    # 第二条宁可要"不那么相关但不一样"的，不要几乎重复的那条
    assert "安卓" in picked[1]["text"]


def test_mmr_handles_empty_and_zero_budget():
    assert rr.mmr([], top_k=3) == []
    assert rr.mmr([{"text": "x", "relevance": 1.0}], top_k=0) == []


# ---------------------------------------------------------------- rerank

def test_rerank_orders_by_fused_relevance_and_truncates():
    items = [{"text": "今天天气不错", "score": 0.2},
             {"text": "用户喜欢用 Python 写脚本", "score": 0.5},
             {"text": "项目用 PyQt5 做界面", "score": 0.6}]
    out = rr.rerank("我用什么语言写脚本", items, top_k=2)
    assert len(out) == 2
    assert "Python" in out[0]["text"]
    assert all("relevance" in row for row in out)


def test_rerank_drops_junk_and_empty():
    junk = [None, "字符串", {}, {"text": "   "},
            {"text": "用户喜欢短句", "score": "abc"}]
    out = rr.rerank("短句", junk, top_k=5)
    assert len(out) == 1
    assert out[0]["text"] == "用户喜欢短句"
    assert out[0]["relevance"] >= 0


def test_rerank_accepts_lexical_overlap_field():
    items = [{"text": "用户喜欢短句", "score": 0.4, "lexical_overlap": 1.0},
             {"text": "项目用 PyQt5", "score": 0.6, "lexical_overlap": 0.0}]
    out = rr.rerank("短句", items, top_k=1)
    assert out[0]["text"] == "用户喜欢短句"


# ---------------------------------------------------------------- 排版

def test_format_passages_numbers_and_sources():
    text = rr.format_passages([
        {"text": "用户早上喝美式咖啡", "source": "记忆"},
        {"text": "项目启动命令：py -3 run.py", "source": "知识库"},
    ])
    assert text.startswith("相关知识：")
    assert "① 用户早上喝美式咖啡（来源：记忆）" in text
    assert "② 项目启动命令：py -3 run.py（来源：知识库）" in text


def test_format_passages_can_hide_source():
    text = rr.format_passages([{"text": "用户喜欢短句", "source": "记忆"}],
                              show_source=False)
    assert "（来源：" not in text
    assert "① 用户喜欢短句" in text


def test_format_passages_empty():
    assert rr.format_passages([]) == ""
    assert rr.format_passages(None) == ""


# ---------------------------------------------------------------- 上下文合并

def test_build_merges_three_sources_into_knowledge_block(tmp_path):
    _write_card(tmp_path, "偏好:喜欢短句")
    trunk = FakeTrunk(
        base=tmp_path,
        modules={"vector_store": _Vs([{"text": "项目启动方式：py -3 run.py",
                                       "score": 0.7}]),
                 "memory_loop": _Ml(),
                 "knowledge_graph": _Kg()},
    )
    ctx = ContextBuilder(trunk).build("我喜欢什么样的句子", is_simple=False)
    assert "相关知识：" in ctx
    assert "①" in ctx
    assert "（来源：记忆）" in ctx
    assert "（来源：知识库）" in ctx
    assert "（来源：知识图谱）" in ctx
    assert "相关知识: 相关知识" not in ctx


def test_ctx_knowledge_respects_top_k_rule(tmp_path):
    trunk = FakeTrunk(base=tmp_path,
                      modules={"vector_store": _Vs([
                          {"text": "条目一", "score": 0.9},
                          {"text": "条目二", "score": 0.8},
                          {"text": "条目三", "score": 0.7},
                      ])},
                      rules={"检索.rerank_top_k": 1})
    ctx = ContextBuilder(trunk)._ctx_knowledge("条目")
    assert "①" in ctx and "②" not in ctx


def test_ctx_knowledge_without_sources_is_empty(tmp_path):
    trunk = FakeTrunk(base=tmp_path, modules={})
    assert ContextBuilder(trunk)._ctx_knowledge("随便问问") == ""


def test_build_simple_input_skips_knowledge(tmp_path):
    trunk = FakeTrunk(base=tmp_path,
                      modules={"vector_store": _Vs([
                          {"text": "用户上次说喜欢简洁", "score": 0.9}])})
    assert ContextBuilder(trunk).build("在吗", is_simple=True) == ""


def test_memory_master_switch_off_skips_v2(tmp_path):
    _write_card(tmp_path, "偏好:喜欢短句")
    trunk = FakeTrunk(base=tmp_path, rules={"记忆.注入": False},
                      modules={"memory_loop": _Ml()})
    ctx = ContextBuilder(trunk).build("我喜欢什么样的句子", is_simple=False)
    assert "【记忆】" not in ctx          # v2 记忆卡不注入
    assert "情景记忆" in ctx             # 旧情景记忆仍在
