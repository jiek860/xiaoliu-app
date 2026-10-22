# -*- coding: utf-8 -*-
"""deep_research 单元测试（mock provider，不发真实网络请求）"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.installed.deep_research import DeepResearch, _BaseProvider


class _MockProvider(_BaseProvider):
    NAME = "mock"
    def search(self, query, n=5):
        return [
            {"标题": f"结果{i} for {query}", "摘要": f"摘要{i}", "链接": f"https://example.com/{i}", "内容": f"内容{i}"}
            for i in range(n)
        ]


class _MockLLM:
    def chat(self, prompt):
        if "拆成" in prompt:
            return "子问题1\n子问题2\n子问题3"
        if "足够" in prompt:
            return "足够"
        return "这是一份测试报告 [1] [2]。"


class _MockTrunk:
    def __init__(self):
        self.modules = {"llm": _MockLLM()}
    def rule(self, *a, **kw):
        return True


def test_init():
    dr = DeepResearch()
    assert dr.NAME == "deep_research"
    assert dr.MAX_HOPS == 3
    assert dr.TIMEOUT == 60.0


def test_tools_declared():
    assert len(DeepResearch.TOOLS) == 1
    t = DeepResearch.TOOLS[0]
    assert t["name"] == "research"
    assert "hints" in t
    assert len(t["hints"]) >= 3


def test_search_with_mock_provider():
    dr = DeepResearch(_MockTrunk())
    dr._providers = [_MockProvider(dr.trunk, "fake-key")]
    results = dr._search("test query", 3)
    assert len(results) == 3
    assert "标题" in results[0]


def test_search_fallback_no_provider():
    dr = DeepResearch(_MockTrunk())
    # 没有 provider，也没有 deep_search module，应该返回空列表不崩
    results = dr._search("test", 3)
    assert isinstance(results, list)


def test_split_subquestions():
    dr = DeepResearch(_MockTrunk())
    subs = dr._split_subquestions("测试主题")
    assert len(subs) >= 1
    assert isinstance(subs[0], str)


def test_research_end_to_end():
    dr = DeepResearch(_MockTrunk())
    dr._providers = [_MockProvider(dr.trunk, "fake-key")]
    result = dr.research("测试主题")
    assert "主题" in result
    assert "报告" in result
    assert "引用" in result
    assert result["结果数"] > 0
    assert result["API模式"] is True


def test_research_no_trunk():
    dr = DeepResearch()
    result = dr.research("测试")
    assert "报告" in result
    assert result["结果数"] == 0  # 没有 trunk 也没有 provider


def test_build_report_format():
    dr = DeepResearch()
    results = [
        {"标题": "A", "摘要": "摘要A", "链接": "https://a.com", "内容": "内容A"},
        {"标题": "B", "摘要": "摘要B", "链接": "https://b.com", "内容": "内容B"},
    ]
    report = dr._build_report("测试", results, 1.5)
    assert report["引用"][0]["ref"] == 1
    assert report["引用"][1]["ref"] == 2
    assert report["耗时秒"] == 1.5


if __name__ == "__main__":
    test_init()
    test_tools_declared()
    test_search_with_mock_provider()
    test_search_fallback_no_provider()
    test_split_subquestions()
    test_research_end_to_end()
    test_research_no_trunk()
    test_build_report_format()
    print("All tests passed!")
