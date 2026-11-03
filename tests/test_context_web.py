# -*- coding: utf-8 -*-
"""联网搜索进上下文的方式 + 影子日志落盘位置（2026-11-01 修"牛头不对马嘴"）。

为什么单独测
------------
用户截图那一串（22:17–22:20）的直接病因有三条，全在这里：

    ① `deep_search.search()` 返回的是 **dict**，代码却 `str(web)[:4000]`
       原样塞进提示词 —— 空结果（`'数量': 0`）也算"非空"，模型看到一坨
       Python 字典字面量，只能瞎猜（"您希望我提供什么样的信息？"）。
    ② 8 秒超时静默返回 `""` —— 模型**不知道"这次没搜到"**，
       于是许空诺（"请稍等片刻，我会尽快为您查询并回复"）。
    ③ 影子日志写 `trunk.base/data` 而不是 `trunk.data_dir` ——
       测试跑真实管线时把假对话写进用户真数据，真实轮次再读它。
"""
import os
import time

from core.pipeline.context_builder import ContextBuilder


class _Search:
    """假装 deep_search 模块（真模块的 search 返回 dict）。"""

    def __init__(self, result):
        self.result = result
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return self.result


class FakeTrunk:
    def __init__(self, base=".", data_dir="", web=None, rules=None):
        self.base = str(base)
        if data_dir:
            self.data_dir = str(data_dir)
        self.config = {"联网": True}
        self.rules = dict(rules or {})
        self.web = web if hasattr(web, "search") else _Search(web)
        self.logs = []
        self.modules = {}

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def _load_lazy(self, name):
        return self.web if name == "deep_search" else None

    def _log(self, msg):
        self.logs.append(str(msg))


def _rows(*titles, snippet=""):
    return [{"来源": "搜狗", "标题": t, "摘要": snippet, "链接": "https://x/" + str(i)}
            for i, t in enumerate(titles)]


# ---------------------------------------------------------------- 落盘位置
def test_shadow_path_follows_data_dir(tmp_path):
    """影子日志跟着 data_dir 走，不能写进 base/data（那可能是用户真数据）"""
    trunk = FakeTrunk(base=str(tmp_path), data_dir=str(tmp_path / "elsewhere"))
    ctx = ContextBuilder(trunk)
    assert ctx.shadow_path() == os.path.join(str(tmp_path), "elsewhere",
                                             "chat_shadow.jsonl")


def test_shadow_path_falls_back_to_base_data(tmp_path):
    """没有 data_dir 的老桩也还能用（保持向后兼容）"""
    ctx = ContextBuilder(FakeTrunk(base=str(tmp_path)))
    assert ctx.shadow_path() == os.path.join(str(tmp_path), "data",
                                             "chat_shadow.jsonl")


# ---------------------------------------------------------------- 查询词清洗
def test_clean_query_strips_politeness():
    ctx = ContextBuilder(FakeTrunk())
    assert ctx.clean_query("可以帮我查看最近的烧烤店吗") == "最近的烧烤店"
    assert ctx.clean_query("请问搜一下 pytest 报错") == "pytest 报错"
    assert ctx.clean_query("菜单") == "菜单"


def test_clean_query_keeps_original_when_nothing_left():
    ctx = ContextBuilder(FakeTrunk())
    assert ctx.clean_query("帮我查") == "帮我查"      # 清空就退回原文
    assert ctx.clean_query("") == ""


def test_clean_query_handles_long_input():
    ctx = ContextBuilder(FakeTrunk())
    assert len(ctx.clean_query("搜一下 " + "烧烤店" * 40)) <= 60


# ---------------------------------------------------------------- 结果进上下文
def test_empty_search_result_tells_model_it_found_nothing():
    """空结果不能变成一坨 dict 字面量，要变成一句"没搜到"的明确提示"""
    trunk = FakeTrunk(web={"结果": [], "总结": "", "数量": 0,
                           "查询": "最近的烧烤店", "来源": []})
    ctx = ContextBuilder(trunk)
    out = ctx._web_search("帮我查一下最近的烧烤店")
    assert "没搜到" in out
    assert "数量" not in out and "{" not in out
    assert "别编" in out


def test_search_rows_are_rendered_as_titles_not_dict():
    trunk = FakeTrunk(web={"结果": _rows("附近烧烤外卖配送电话 — 58同城",
                                         "烧烤店推荐 - 大众点评"),
                           "总结": "", "数量": 2, "查询": "烧烤店", "来源": []})
    ctx = ContextBuilder(trunk)
    out = ctx._web_search("帮我搜一下烧烤店")
    assert "抓到 2 条" in out
    assert "58同城" in out and "大众点评" in out
    assert "不可信" in out or "UNTRUSTED" in out


def test_rows_without_title_are_dropped():
    trunk = FakeTrunk(web={"结果": [{"来源": "搜狗", "标题": "", "摘要": "空标题"}],
                           "总结": "", "数量": 1})
    ctx = ContextBuilder(trunk)
    assert "没搜到" in ctx._web_search("帮我查一下最近的烧烤店")


def test_local_question_gets_location_note():
    """问"附近"时模型要说清没有定位，别假装知道在哪"""
    trunk = FakeTrunk(web={"结果": _rows("烧烤店"), "总结": "", "数量": 1})
    ctx = ContextBuilder(trunk)
    out = ctx._web_search("帮我查一下附近有哪些烧烤店")
    assert "定位" in out


def test_no_web_when_query_is_not_a_fact_check():
    ctx = ContextBuilder(FakeTrunk(web={"结果": _rows("x"), "数量": 1}))
    assert ctx._web_search("我今天有点累") == ""


# ---------------------------------------------------------------- 超时
def test_bounded_timeout_returns_fallback_not_empty():
    trunk = FakeTrunk()
    ctx = ContextBuilder(trunk)

    def slow():
        time.sleep(0.5)
        return "太晚了"

    assert ctx._bounded(slow, 0.05, "联网搜索", "我超时了") == "我超时了"
    assert any("超过" in row for row in trunk.logs)


def test_build_tells_model_when_search_times_out():
    """超时也要留一句"没搜到"，否则模型只能许空诺"""

    class SlowSearch:
        def search(self, query):
            time.sleep(1.0)
            return {"结果": [], "总结": "", "数量": 0}

    trunk = FakeTrunk(web=SlowSearch())
    ctx = ContextBuilder(trunk)
    ctx._WEB_BUDGET = 0.05
    out = ctx.build("帮我查一下最近的烧烤店", is_simple=True)
    assert "没搜到" in out
    assert "超时" in out or "没回来" in out


def test_build_without_web_need_adds_nothing():
    ctx = ContextBuilder(FakeTrunk(web={"结果": _rows("x"), "数量": 1}))
    assert ctx.build("嗯", is_simple=True) == ""