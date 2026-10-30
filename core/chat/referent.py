# -*- coding: utf-8 -*-
"""指代消解：把「它 / 这个 / 继续」补全成上一轮的话题。

为什么做
--------
用户连续对话时很少重复名词（"帮我改改它" "继续"），直接把原话丢给模型，
模型拿不到指代对象就开始猜。这里在发送前把指代补成
``「上一轮话题」``，并给用户一行系统提示，透明可撤销。

约束：纯函数、规则式；拿不到话题就原样返回，绝不编造。
"""
from __future__ import annotations

from core.chat import topic_index

# 长词在前：先匹配「上面说的」，避免被更短的「上面」抢先替换
PRONOUNS = ("上面说的", "刚才那个", "刚才说的", "这段代码", "这个文件",
            "它", "他", "她", "这个", "那个", "这些", "那些",
            "上面", "刚才")
CONTINUATIONS = ("继续", "接着", "再来一次", "再试一次", "继续刚才的")


def last_topic(messages):
    """最近一条消息的话题词（优先助手回复里的关键词）。"""
    for msg in reversed(list(messages or [])):
        topic = topic_index.topic_of(msg)
        if topic:
            return topic
    return ""


def resolve(text, messages):
    """返回 ``{text, changed, topic, note}``；没有指代时 changed=False。"""
    text = str(text or "")
    stripped = text.strip()
    if not stripped:
        return {"text": text, "changed": False, "topic": "", "note": ""}
    topic = last_topic(messages)
    if not topic:
        return {"text": text, "changed": False, "topic": "", "note": ""}
    if any(word in stripped for word in CONTINUATIONS) and \
            len(stripped) <= 12:
        new = stripped + "（接续话题：%s）" % topic
        return {"text": new, "changed": True, "topic": topic,
                "note": "已把「%s」接到「%s」" % (stripped, topic)}
    for word in PRONOUNS:
        if word in stripped:
            new = stripped.replace(word, "「%s」" % topic, 1)
            return {"text": new, "changed": True, "topic": topic,
                    "note": "已把「%s」补全为「%s」" % (word, topic)}
    return {"text": text, "changed": False, "topic": topic, "note": ""}
