# -*- coding: utf-8 -*-
"""``core.tts_text.naturalize``：朗读前把"给眼睛看的"排版洗成"能读的话"。

2026-11-01 用户反馈"语音能不能更像真人一点"。除了音色本身，
最大的"假感"来源是把 ** 加粗、``` 代码块 ```、😊、链接原样丢给 TTS：
符号被念出来、代码念成天书、在不该断的地方硬断。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.tts_text import naturalize  # noqa: E402


def test_markdown_markers_are_stripped_but_words_kept():
    out = naturalize("**重点**是：今天先做 `tts` 这块，_不要_跳过。")
    assert "重点" in out and "tts" in out
    for mark in ("**", "`", "_不要_"):
        assert mark not in out


def test_code_block_is_skipped():
    text = "先看代码：\n```python\nprint('hello')\n```\n然后跑一下。"
    out = naturalize(text)
    assert "print" not in out, "代码块不能念出来"
    assert "先看代码" in out and "然后跑一下" in out


def test_emoji_and_url_are_removed():
    out = naturalize("搞定了 😊🎉 细节见 https://example.com/x 谢谢你！")
    assert "😊" not in out and "🎉" not in out
    assert "http" not in out
    assert "搞定了" in out and "谢谢你" in out


def test_newline_becomes_pause_not_double_punct():
    out = naturalize("第一句\n第二句\n\n第三句")
    assert out.count("。") >= 2, "换行要变成停顿"
    assert "。。" not in out and "，。" not in out


def test_trailing_punct_is_added():
    assert naturalize("今天天气不错") == "今天天气不错。"
    assert naturalize("你好吗？") == "你好吗？"


def test_heading_quote_bullet_are_removed():
    out = naturalize("# 标题\n> 引用\n- 第一项\n- 第二项")
    assert "#" not in out and ">" not in out
    assert "标题" in out and "第一项" in out


def test_cjk_spaces_are_collapsed():
    assert "你 好" not in naturalize("你 好 呀")


def test_long_text_cut_at_sentence_boundary():
    text = "第一句。" * 40
    out = naturalize(text, 30)
    assert len(out) <= 30
    assert out.endswith("。"), "不能在半个词上断"


def test_empty_and_symbol_only_return_empty():
    assert naturalize("") == ""
    assert naturalize("   \n\t ") == ""
    assert naturalize("😊🎉") == ""


def test_emoji_becomes_pause_not_glue():
    """emoji 删掉会把两句粘成一句（"搞定啦三步走"）；换成逗号更像换气。"""
    out = naturalize("**搞定啦** 😊 三步走：")
    assert "搞定啦，三步走" in out
    assert "搞定啦三步走" not in out


def test_numbered_list_markers_are_removed():
    """'1. 打开设置' 不能念成'一。打开设置'。"""
    out = naturalize("1. 打开设置\n2. 找到组件页\n3) 点一键安装")
    assert "1。" not in out and "2。" not in out and "3。" not in out
    assert "打开设置" in out and "点一键安装" in out


def test_plain_sentence_kept_as_is():
    src = "好呀，我在呢。今天想聊点什么？"
    assert naturalize(src) == src
