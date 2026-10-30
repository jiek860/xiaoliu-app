# -*- coding: utf-8 -*-
"""聊天话题索引：从会话消息里抽关键词，供话题时间线 / 指代消解使用。

为什么不用模型抽话题
--------------------
话题导航是本地、即时、零成本的辅助功能；每条消息都调一次模型抽话题，
既慢又花钱。这里用启发式（中文按标点切块 + 英文单词），够用且可测。

约束：纯函数，不读数据库、不调模型；消息统一接受
``{"role"/"r": "u"/"a", "text"/"content": "..."}`` 两种写法。
"""
from __future__ import annotations

import re

MAX_TOPIC_LEN = 12
MAX_TOPICS = 12

_STOP = set("""
我 你 他 她 它 我们 你们 他们 这个 那个 这些 那些 的 了 着 吗 呢 吧 啊
帮我 看看 试试 一下 一个 什么 怎么 为什么 多少 是不是 有没有
是 不 有 没 在 和 与 或 就 都 也 还 又 很 太 更 最
可以 能 会 要 想 请 帮 把 给 让 对 从 到 用 说 看 做 个 这 那 里 上 下
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]{2,}|[\u4e00-\u9fff]{2,8}")
_SPLIT_RE = re.compile(r"[\s，。！？；：、,.!?;:\"'“”‘’（）()\[\]{}<>《》/\\|=+*~`@#$%^&]+")
_SENTENCE_RE = re.compile(r"[。！？；!?;\n]")


def _text(msg):
    if isinstance(msg, str):
        return msg
    msg = msg or {}
    return str(msg.get("text") or msg.get("content") or "")


def _role(msg):
    if isinstance(msg, str):
        return "u"
    msg = msg or {}
    return str(msg.get("role") or msg.get("r") or msg.get("type") or "")


def keywords(text, limit=4):
    """从一段话里抽 1-4 个候选话题词（长的在前，去停用词）。"""
    out = []
    for chunk in _SPLIT_RE.split(str(text or ""))[:40]:
        for token in _TOKEN_RE.findall(chunk):
            token = token.strip("_-.")
            if len(token) < 2 or token.lower() in _STOP:
                continue
            if token in _STOP or token in out:
                continue
            out.append(token)
    out.sort(key=lambda s: (-len(s), s))
    return out[:max(1, int(limit or 1))]


def first_sentence(text, limit=MAX_TOPIC_LEN):
    """消息的第一句 / 第一个短块：话题名比关键词更像人话。"""
    text = str(text or "").strip()
    if not text:
        return ""
    head = _SENTENCE_RE.split(text, 1)[0].strip()
    head = re.sub(r"^(帮我|请|麻烦|我想|我要)+", "", head)
    head = head.strip("：:，, ")
    if len(head) <= limit:
        return head
    return head[:limit]


def topics(messages, max_topics=MAX_TOPICS):
    """按出现顺序聚合话题：``[{topic, count, first, last, index}]``。

    用户消息优先（模型回复里的关键词太泛）；同名话题合并计数，
    ``index`` 是该话题第一次出现的消息下标，供时间线跳转。
    """
    merged, order = {}, []
    for i, msg in enumerate(messages or []):
        role = _role(msg)
        if role and role not in ("u", "user", "human"):
            continue
        topic = first_sentence(_text(msg))
        if not topic or topic in _STOP:
            continue
        if topic not in merged:
            merged[topic] = {"topic": topic, "count": 0,
                             "first": i, "last": i, "index": i}
            order.append(topic)
        merged[topic]["count"] += 1
        merged[topic]["last"] = i
    items = [merged[t] for t in order]
    items.sort(key=lambda x: (-x["count"], x["first"]))
    return items[:max(1, int(max_topics or 1))]


def search(items, query):
    """在话题列表里按子串过滤（大小写不敏感，空查询返回全部）。"""
    q = str(query or "").strip().lower()
    if not q:
        return list(items or [])
    return [x for x in (items or []) if q in str(x.get("topic", "")).lower()]


def summary(items, limit=MAX_TOPICS):
    """话题清单压成文字（时间线窗口顶部的一行概述）。"""
    items = list(items or [])[:limit]
    if not items:
        return "还没有可导航的话题"
    return " · ".join("%s(%d)" % (x.get("topic"), x.get("count", 1))
                      for x in items)


def topic_of(msg):
    """单条消息的话题名（给回复动作「继续这个话题」用）。"""
    text = _text(msg)
    names = keywords(text, limit=3)
    return names[0] if names else first_sentence(text)
