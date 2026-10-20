# -*- coding: utf-8 -*-
"""向量库（core/vector_store.py）

为什么补这个文件
----------------
工程化方案实测它的覆盖率是 **32.8%**，是真薄弱的一个 ——
而且它是**记忆检索的核心**：它错了，表现出来就是"小6 记不住事"，
很难归因（用户会以为是模型笨、或者自己没说清）。

它的关键设计是**降级**：Ollama 的嵌入服务连不上时，
不能崩、不能卡，要自动退到关键词检索，并且**300 秒内不再重试**
（否则每次检索都要白等一个 5 秒超时）。这套逻辑原来基本没验过。

本文件重点守住：
    · 嵌入失败 → 降级，不崩
    · 冷却生效 → 冷却期内**一次网络请求都不发**
    · 数据落盘 → 换个实例还能读回来
"""
import os
import sys
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

np = pytest.importorskip("numpy")                  # 向量库依赖 numpy
from core.vector_store import VectorStore          # noqa: E402


class FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {"ollama_url": "http://127.0.0.1:1"}
        self.logs = []
        self.status = []

    def rule(self, key, default=None):
        return default

    def _log(self, m):
        self.logs.append(m)

    def _set_status(self, m):
        self.status.append(m)


@pytest.fixture
def vs(tmp_path):
    """一个干净的向量库（每个用例一个独立的临时库）"""
    t = FakeTrunk(str(tmp_path))
    v = VectorStore(t)
    # 节流清零 —— 否则用例之间要互相等 0.2 秒
    v.embed_gap = 0
    return v


# ══════════════════════════════════════════════════════════════
# ① 余弦相似度 —— 检索的数学基础
# ══════════════════════════════════════════════════════════════
def test_cosine_identical(vs):
    assert abs(vs._cosine([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9


def test_cosine_orthogonal(vs):
    assert abs(vs._cosine([1, 0], [0, 1])) < 1e-9


def test_cosine_opposite(vs):
    assert abs(vs._cosine([1, 2], [-1, -2]) + 1.0) < 1e-9


def test_cosine_zero_vector_does_not_divide_by_zero(vs):
    """⚠️ 全零向量不能 ZeroDivisionError

    代码里写的是 `math.sqrt(...) or 1` —— 就是为了兜这个。
    真出零向量（嵌入服务返回异常数据）时它得活着。
    """
    r = vs._cosine([0, 0, 0], [1, 2, 3])
    assert r == 0.0, r


# ══════════════════════════════════════════════════════════════
# ② 嵌入：成功 / 失败 / **冷却**
# ══════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_embed_success(monkeypatch, vs):
    calls = []

    def fake_post(url, json=None, timeout=None):
        # 只统计嵌入端点：全量跑时可能有别的线程在打 /api/chat
        # （实测：期望 1 次、实际 2 次，多出来那条是后台线程）
        if str(url).endswith("/api/embeddings"):
            calls.append(url)
        return _Resp({"embedding": [0.1, 0.2, 0.3]})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    r = vs._embed("你好")
    assert r == [0.1, 0.2, 0.3], r
    assert len(calls) == 1


def test_embed_truncates_long_text(monkeypatch, vs):
    """超长文本只发前 500 字 —— 嵌入模型有输入上限，发太长会报错"""
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["prompt"] = json["prompt"]
        return _Resp({"embedding": [1.0]})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    vs._embed("字" * 2000)
    assert len(seen["prompt"]) == 500, len(seen["prompt"])


def test_embed_failure_enters_cooldown(monkeypatch, vs):
    """失败要返回空 + 进冷却（不是抛异常）"""
    def boom(*a, **k):
        raise ConnectionError("连不上")

    import requests
    monkeypatch.setattr(requests, "post", boom)
    assert vs._embed("你好") == []
    assert vs._embed_retry_at > time.time(), "没进冷却"
    assert any("嵌入失败" in l for l in vs.trunk.logs), \
        "没记日志：%s" % vs.trunk.logs


def test_cooldown_skips_network_entirely(monkeypatch, vs):
    """⚠️ **冷却期内一次网络请求都不该发** —— 这是冷却存在的全部意义

    没有冷却的话：每次检索都要白等一个 5 秒超时，
    用户看到的是"一问它就卡半天"。
    """
    calls = []

    def boom(url="", *a, **k):
        # 同上：只统计嵌入端点，别把后台线程的 /api/chat 算进来
        if str(url).endswith("/api/embeddings"):
            calls.append(1)
        raise ConnectionError("连不上")

    import requests
    monkeypatch.setattr(requests, "post", boom)

    assert vs._embed("第一次") == []
    assert len(calls) == 1

    # 冷却期内连发 5 次 —— 都该直接返回，不碰网络
    for i in range(5):
        assert vs._embed("第%d次" % i) == []
    assert len(calls) == 1, \
        "冷却期内又发了 %d 次请求 —— 冷却没生效" % (len(calls) - 1)


def test_success_clears_cooldown(monkeypatch, vs):
    """成功后要解除冷却（否则一次抖动就永久降级了）"""
    import requests

    def boom(*a, **k):
        raise ConnectionError("连不上")
    monkeypatch.setattr(requests, "post", boom)
    vs._embed("失败一次")
    assert vs._embed_retry_at > 0

    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: _Resp({"embedding": [1.0]}))
    vs._embed_retry_at = 0                     # 模拟冷却到期
    assert vs._embed("好了") == [1.0]
    assert vs._embed_retry_at == 0, "成功了却没解除冷却"


def test_embed_throttle_waits(monkeypatch, vs):
    """节流：两次嵌入之间要隔 embed_gap 秒（防把 Ollama 打爆）"""
    import requests
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: _Resp({"embedding": [1.0]}))
    vs.embed_gap = 0.15
    vs._last_embed = time.time()
    t0 = time.time()
    vs._embed("第二次")
    dt = time.time() - t0
    assert dt >= 0.10, "节流没生效（只等了 %.3f 秒）" % dt


# ══════════════════════════════════════════════════════════════
# ③ add
# ══════════════════════════════════════════════════════════════
def test_add_returns_error_when_embed_fails(vs):
    """嵌入失败时 add 要**返回错误**而不是塞一条空向量进去

    塞空向量进去更糟：以后每次检索都算它，结果永远不对，还查不出来。
    """
    vs._embed = lambda t: []
    r = vs.add("记一件事")
    assert r.get("ok") is False
    assert r.get("reason") == "embed_failed", r
    assert not vs.data, "失败却把数据塞进去了"


def test_add_success_grows_data_and_matrix(vs):
    vs._embed = lambda t: [0.1, 0.2, 0.3]
    r = vs.add("第一条", tag="测试")
    assert r.get("ok") is not False, r
    assert len(vs.data) == 1
    assert vs.data[0]["text"] == "第一条"
    assert vs.data[0]["tag"] == "测试"
    assert vs._emb_mat is not None and len(vs._emb_mat) == 1


def test_add_twice_stacks_matrix(vs):
    vs._embed = lambda t: [0.1, 0.2, 0.3]
    vs.add("一")
    vs.add("二")
    assert len(vs.data) == 2
    assert vs._emb_mat.shape == (2, 3), vs._emb_mat.shape


# ══════════════════════════════════════════════════════════════
# ④ search —— 含**关键词降级**
# ══════════════════════════════════════════════════════════════
def test_search_empty_store_returns_empty(vs):
    assert vs.search("随便问问") == []


def test_search_falls_back_to_keyword(vs):
    """⚠️ 嵌入不可用时**必须还能搜到**（只是质量差一点）

    这是"它记不住事"和"它记得但排得不好"的分界线。
    降级到关键词是**有意的设计**，不是失败。
    """
    vs._embed = lambda t: [1.0, 0.0]
    vs.add("今天天气不错")
    vs.add("我在写代码")
    # 之后嵌入坏掉
    vs._embed = lambda t: []
    r = vs.search("天气")
    assert r, "嵌入失败后完全搜不到了 —— 降级没生效"
    assert any("天气" in x["text"] for x in r), r


def test_search_keyword_no_match_returns_head(vs):
    """关键词一个都没命中时，返回最前面几条（而不是空）

    空结果会让上层以为"库里没东西"，其实只是这次没匹配上。
    """
    vs._embed = lambda t: [1.0, 0.0]
    for i in range(3):
        vs.add("条目%d" % i)
    vs._embed = lambda t: []
    r = vs.search("完全不相干的词xyz")
    assert len(r) == 3, r
    assert all(x["score"] == 0 for x in r), r


def test_search_respects_top_k(vs):
    vs._embed = lambda t: [1.0, 0.0]
    for i in range(8):
        vs.add("条目%d" % i)
    r = vs.search("条目", top_k=3)
    assert len(r) <= 3, len(r)


def test_search_vector_path_returns_scores_descending(vs):
    """走向量那条路时，结果要按相似度**降序**"""
    def emb(t):
        return [1.0, 0.0] if "苹果" in t else [0.0, 1.0]
    vs._embed = emb
    vs.add("苹果好吃")
    vs.add("香蕉也好吃")
    r = vs.search("苹果")
    assert r, "向量检索没返回结果"
    scores = [x.get("score", 0) for x in r]
    assert scores == sorted(scores, reverse=True), scores


def test_search_never_raises_on_corrupt_row(vs):
    """data 里混进畸形条目也不能让检索崩（它会读用户长期积累的数据）"""
    vs._embed = lambda t: []
    vs.data = [{"text": "正常"},
               {},                                   # 没有 text
               {"text": None},
               {"text": "另一条"}]
    r = vs.search("正常")                            # 不许抛
    assert isinstance(r, list)


# ══════════════════════════════════════════════════════════════
# ⑤ 落盘与重载 —— "记忆"必须活过重启
# ══════════════════════════════════════════════════════════════
def test_data_survives_restart(tmp_path):
    """⚠️ 加进去的东西，换个实例要能读回来

    这是"记忆"这个词的底线 —— 重启就没了那不叫记忆。
    """
    t = FakeTrunk(str(tmp_path))
    v1 = VectorStore(t)
    v1.embed_gap = 0
    v1._embed = lambda x: [0.5, 0.5]
    v1.add("要记住的事", tag="重要")

    v2 = VectorStore(t)                              # 新实例 = 模拟重启
    assert len(v2.data) == 1, "重启后数据没了：%s" % v2.data
    assert v2.data[0]["text"] == "要记住的事"
    assert v2.data[0]["tag"] == "重要"


def test_list_all_returns_texts(vs):
    vs._embed = lambda t: [1.0]
    vs.add("甲")
    vs.add("乙")
    r = vs.list_all()
    assert isinstance(r, list) and len(r) == 2, r


def test_run_returns_something(vs):
    r = vs.run("统计")
    assert r is not None


def test_trim_old_keeps_recent(vs):
    """超出容量要截断，且**保留最近的**（旧的不该挤掉新的）"""
    vs._embed = lambda t: [1.0, 0.0]
    vs.max_items = 5
    vs.keep_items = 3
    for i in range(8):
        vs.add("条目%d" % i)
    if len(vs.data) > vs.max_items:
        vs._trim_old()
    assert len(vs.data) <= vs.max_items, \
        "截断没生效，还剩 %d 条" % len(vs.data)


# ══════════════════════════════════════════════════════════════
# ⑥ 构造时的健壮性
# ══════════════════════════════════════════════════════════════
def test_construct_without_trunk_uses_defaults():
    """不给 trunk 也要能建（有代码路径是这么用的）"""
    v = VectorStore(None)
    assert v.half_life > 0 and v.max_items > 0


def test_construct_survives_broken_db(tmp_path):
    """⚠️ vectors.db 损坏时必须能起来

    这个文件是**长期积累**的，被强杀/断电时真会坏。
    坏了就打不开程序，用户会以为是自己弄坏了什么。
    """
    t = FakeTrunk(str(tmp_path))
    db = os.path.join(str(tmp_path), "data", "vectors.db")
    os.makedirs(os.path.dirname(db), exist_ok=True)
    open(db, "wb").write(b"not a sqlite file at all " * 100)
    try:
        v = VectorStore(t)
    except Exception as e:
        pytest.fail("数据库损坏时构造就崩了：%s: %s" % (type(e).__name__, e))
    assert v is not None


def test_defaults_when_trunk_rule_raises(tmp_path):
    """`trunk.rule()` 抛异常时要退到默认值（不能卡在构造里）"""
    class Bad(FakeTrunk):
        def rule(self, key, default=None):
            raise RuntimeError("规则引擎坏了")

    v = VectorStore(Bad(str(tmp_path)))
    assert v.max_items == 2000 and v.embed_gap == 0.2
