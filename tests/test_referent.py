# -*- coding: utf-8 -*-
"""指代消解：把「它/这个/继续」补成上一轮话题。"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.chat import referent  # noqa: E402

MSGS = [{"role": "u", "text": "贪吃蛇游戏"},
        {"role": "a", "text": "好的，已经给你写好了"}]


def test_last_topic_picks_most_recent():
    assert referent.last_topic(MSGS)
    assert referent.last_topic([]) == ""


def test_resolve_pronoun_replaces_once():
    r = referent.resolve("把它改成加速版", MSGS)
    assert r["changed"] is True
    assert "它" not in r["text"].replace("其它", "")
    assert "「" in r["text"] and r["topic"]


def test_resolve_continuation_appends_topic():
    r = referent.resolve("继续", MSGS)
    assert r["changed"] is True
    assert r["text"].startswith("继续（接续话题：")


def test_resolve_without_topic_or_pronoun_is_unchanged():
    assert referent.resolve("你好", [])["changed"] is False
    r = referent.resolve("今天天气不错", MSGS)
    assert r["changed"] is False and r["text"] == "今天天气不错"


def test_resolve_empty_text():
    assert referent.resolve("", MSGS)["changed"] is False
