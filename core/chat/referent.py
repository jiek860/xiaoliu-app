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

import re

from core.chat import topic_index

# 长词在前：先匹配「上面说的」，避免被更短的「上面」抢先替换
PRONOUNS = ("上面说的", "刚才那个", "刚才说的", "这段代码", "这个文件",
            "它", "他", "她", "这个", "那个", "这些", "那些",
            "上面", "刚才")
CONTINUATIONS = ("继续", "接着", "再来一次", "再试一次", "继续刚才的")

# 批次 D12：序数 / 方位指代（"第三个方案""上面那个函数""之前那个文件"）
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
ORDERED_RE = re.compile(
    r"第\s*(?P<num>[一二三四五六七八九十0-9]+)\s*"
    r"(?P<unit>个|条|种)?\s*"
    r"(?P<noun>方案|函数|文件|版本|方法|话题|问题|建议)?")
DIRECTION_RE = re.compile(
    r"(?P<prev>上一个|前面那个|上面那个|之前那个|刚才那个)"
    r"(?P<pnoun>文件|函数|方案|版本|方法|话题|问题)?"
    r"|(?P<next>下一个|后面那个)"
    r"(?P<nnoun>文件|函数|方案|版本|方法|话题|问题)?")


def _number(text):
    text = str(text or "").strip()
    if text.isdigit():
        return int(text)
    if text in _CN_NUM:
        return _CN_NUM[text]
    if text.startswith("十"):
        return 10 + _CN_NUM.get(text[1:], 0)
    return 0


def _ordered_entity(items, noun, number):
    """「第 N 个方案/函数…」→ 话题实体；同类不够时退回全部话题按出现顺序。

    这样「第三个方案」即使历史话题里没写「方案」二字也能落到第 3 个用户
    话题，而不是原样丢给模型猜。
    """
    pool = [x for x in items if noun and noun in str(x.get("topic", ""))] \
        or list(items)
    pool = sorted(pool, key=lambda x: x.get("index", 0))
    if not pool:
        return ""
    if number:
        return str(pool[min(number - 1, len(pool) - 1)].get("topic", ""))
    return str(pool[0].get("topic", ""))


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
    # 批次 D12：先跑序数 / 方位指代，命中就回填对应话题实体。
    try:
        items = topic_index.topics(messages, max_topics=12)
    except Exception:
        items = []
    ordered = sorted(items, key=lambda x: x.get("index", 0))
    match = ORDERED_RE.search(stripped)
    if match and not (match.group("unit") or match.group("noun")):
        match = None
    if match:
        number = _number(match.group("num"))
        entity = _ordered_entity(ordered, match.group("noun") or "", number)
        if entity:
            new = stripped.replace(match.group(0), "「%s」" % entity, 1)
            return {"text": new, "changed": True, "topic": entity,
                    "note": "已把「%s」补全为「%s」" % (match.group(0), entity)}
    direction = DIRECTION_RE.search(stripped)
    if direction:
        noun = direction.group("pnoun") or direction.group("nnoun") or ""
        entity = ""
        if direction.group("prev"):
            older = [x for x in ordered if noun in str(x.get("topic", ""))] \
                or ordered
            entity = str(older[-2].get("topic", "")) if len(older) >= 2 else (
                str(older[-1].get("topic", "")) if older else "")
        elif ordered:
            entity = str(ordered[-1].get("topic", ""))
        if entity:
            new = stripped.replace(direction.group(0), "「%s」" % entity, 1)
            return {"text": new, "changed": True, "topic": entity,
                    "note": "已把「%s」补全为「%s」" % (
                        direction.group(0), entity)}
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
