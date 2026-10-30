# -*- coding: utf-8 -*-
"""话题索引：关键词、话题聚合、过滤与概述。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.chat import topic_index as ti  # noqa: E402


def test_keywords_filters_stopwords_and_orders_by_length():
    words = ti.keywords("帮我 看看 这个 贪吃蛇 报表")
    assert "贪吃蛇" in words and "报表" in words
    assert "帮我" not in words and "这个" not in words


def test_first_sentence_strips_politeness_and_truncates():
    assert ti.first_sentence("帮我写个贪吃蛇游戏。") == "写个贪吃蛇游戏"
    long = ti.first_sentence("x" * 40)
    assert len(long) == ti.MAX_TOPIC_LEN


def test_topics_merges_same_topic_and_orders_by_count():
    msgs = [{"role": "u", "text": "帮我写个贪吃蛇游戏"},
            {"role": "u", "text": "帮我写个贪吃蛇游戏"},
            {"role": "a", "text": "好的"},
            {"role": "u", "text": "再做个报表"}]
    items = ti.topics(msgs)
    top = items[0]
    assert top["topic"] == "写个贪吃蛇游戏" and top["count"] == 2
    assert top["index"] == 0


def test_topics_accepts_plain_strings_and_skips_empty():
    items = ti.topics(["", "报表", None])
    assert [x["topic"] for x in items] == ["报表"]


def test_search_and_summary():
    items = [{"topic": "贪吃蛇", "count": 2, "index": 0},
             {"topic": "报表", "count": 1, "index": 2}]
    assert ti.search(items, "") == items
    assert ti.search(items, "报表") == [items[1]]
    assert "贪吃蛇(2)" in ti.summary(items)
    assert ti.summary([]) == "还没有可导航的话题"


def test_topic_of_message():
    assert ti.topic_of({"text": "贪吃蛇游戏"}) == "贪吃蛇游戏"
    assert ti.topic_of({"text": ""}) == ""
