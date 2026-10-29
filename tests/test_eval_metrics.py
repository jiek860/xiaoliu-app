# -*- coding: utf-8 -*-
"""评测指标纯函数（批次 41.1）。"""
from tools.eval_metrics import (banned_hits, char_count, emoji_count, eval_chat,
                                ngram_repeat_rate, question_count,
                                sentence_count)


def test_sentence_count_mixed_punctuation():
    assert sentence_count("好的。") == 1
    assert sentence_count("先这样！再那样？") == 2
    assert sentence_count("第一句. 第二句") == 2
    assert sentence_count("") == 0


def test_char_count_ignores_spaces():
    assert char_count(" 你好 世界 ") == 4


def test_emoji_and_question_count():
    assert emoji_count("好耶😀") == 1
    assert emoji_count("没有表情") == 0
    assert question_count("真的？为什么?") == 2


def test_banned_hits_keeps_table_order():
    hits = banned_hits("作为AI，我不能", ["我不能", "作为AI"])
    assert hits == ["我不能", "作为AI"]
    assert banned_hits("普通回复", ["作为AI"]) == []


def test_ngram_repeat_rate_detects_copypaste():
    one = "这是一段用来测试重复率的中文文本，长度足够生成八连字。"
    assert ngram_repeat_rate([one], n=8) == 0.0
    assert ngram_repeat_rate([one + one], n=8) > 0.3
    assert ngram_repeat_rate([], n=8) == 0.0


def test_eval_chat_short_answer_pass():
    out = eval_chat("累就先歇会儿，我在。",
                    {"max_sentences": 2, "max_chars": 30,
                     "must_not": ["作为AI"], "must_include_any": ["歇", "我在"]})
    assert out["ok"] is True
    assert out["issues"] == []
    assert out["metrics"]["sentences"] == 1


def test_eval_chat_reports_all_issues():
    text = "作为AI，首先你应该冷静。然后你应该早睡。最后还要多喝水。"
    out = eval_chat(text, {"max_sentences": 1, "max_chars": 20,
                           "must_not": ["作为AI", "你应该"],
                           "must_include_any": ["歇", "我在"]})
    assert out["ok"] is False
    joined = "；".join(out["issues"])
    assert "句子过多" in joined
    assert "字数过多" in joined
    assert "命中禁语" in joined
    assert "缺少要点" in joined


def test_eval_chat_empty_expect_always_pass():
    assert eval_chat("随便一句", {})["ok"] is True
