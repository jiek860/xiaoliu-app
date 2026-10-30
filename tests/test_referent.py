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


# ---------------- 批次 D12：序数 / 方位指代 ----------------
TOPICS = [{"role": "u", "text": "贪吃蛇游戏"},
          {"role": "u", "text": "登录页面"},
          {"role": "u", "text": "导出报表"},
          {"role": "a", "text": "好了"}]


def test_ordered_reference_picks_nth_topic():
    r = referent.resolve("把第三个方案改快一点", TOPICS)
    assert r["changed"] is True
    assert r["topic"] == "导出报表"
    assert "「导出报表」" in r["text"]
    assert "第三个方案" not in r["text"]


def test_ordered_reference_with_digit():
    r = referent.resolve("第2个版本也改一下", TOPICS)
    assert r["changed"] is True and r["topic"] == "登录页面"


def test_direction_previous_picks_second_last_topic():
    r = referent.resolve("上一个那个文件的写法也补上", TOPICS)
    assert r["changed"] is True
    assert "「登录页面」" in r["text"]


def test_direction_next_uses_latest_topic():
    r = referent.resolve("下一个方案继续做", TOPICS)
    assert r["changed"] is True and r["topic"] == "导出报表"


def test_ordered_reference_without_topics_is_unchanged():
    assert referent.resolve("第三个方案", [])["changed"] is False
    assert referent.resolve("第三个方案", [])["text"] == "第三个方案"


def test_ordered_number_parsing():
    assert referent._number("三") == 3
    assert referent._number("12") == 12
    assert referent._number("十一") == 11
    assert referent._number("随便") == 0
    # 没有量词/名词的「第三章」不当指代处理，避免误伤
    assert referent.resolve("第三章讲什么", TOPICS)["changed"] is False
