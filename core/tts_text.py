# -*- coding: utf-8 -*-
"""朗读前的文本清洗：把"给眼睛看的回复"变成"适合读出来的话"。

为什么需要
----------
聊天回复里混着大量排版符号：``**加粗**``、``# 标题``、``- 列表``、
`````代码块`````、``😊``、``https://…``。直接丢给 edge-tts 会出三种毛病：

* 符号被念出来（"星号""井号"）或在不该断的地方硬断；
* 代码块整段念成天书（几十秒噪音，用户以为卡住了）；
* emoji 变成莫名其妙的停顿或英文单词。

清洗只做"去掉不能读的"，不改用户真正想听的内容：
代码块整段跳过、链接跳过、emoji 去掉、排版符号去掉，
换行变成句号（停顿更像人说话），最后补齐句末标点（语调才收得住）。

对外只有一个函数 ``naturalize(text, limit=500)``。
"""
from __future__ import annotations

import re

# 句末标点：用来判断"这句话收住了没有"
_END_PUNCT = "。！？!?…~～"
# 中文字符范围（判断"要不要去掉中间的空格"）
_CJK = "\u4e00-\u9fff"

# emoji / 象形符号 / 变体选择符 / 零宽连接符（念出来只会是噪音）
_RE_EMOJI = re.compile(
    "[" "\U0001F000-\U0001FAFF" "\U00002190-\U000021FF"
    "\U00002600-\U000027BF" "\U00002B00-\U00002BFF"
    "\uFE00-\uFE0F" "\u200D" "\u20E3" "]")

_RE_CODE_BLOCK = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_RE_URL = re.compile(r"(?:https?|ftp)://\S+")
_RE_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_RE_INLINE_CODE = re.compile(r"`([^`]*)`")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
# 下划线强调（_不要_）：只去掉"贴着中文"的下划线，
# 这样 `tts_voice` 这类标识符不会被拆成 `ttsvoice`（念出来就错了）
_RE_UNDER_CJK = re.compile(r"_(?=[%s])|(?<=[%s])_" % (_CJK, _CJK))
_RE_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_RE_QUOTE = re.compile(r"(?m)^\s{0,3}>\s*")
_RE_BULLET = re.compile(r"(?m)^\s*[-*•·]\s+")
# 有序列表标记（"1. 打开设置" → "打开设置"）：
# 不处理会被 "." → "。" 变成"一。打开设置"，念出来很怪
_RE_NUM_BULLET = re.compile(r"(?m)^\s*\d{1,3}\s*[.、)）]\s+")
_RE_STARS = re.compile(r"[*]+")


def _tidy_punct(text):
    """收拾清洗过程留下的重复/错位标点。"""
    text = text.replace(",", "，").replace(".", "。")
    text = re.sub(r"[，、]{2,}", "，", text)
    text = re.sub(r"[，、]+([。！？])", r"\1", text)
    text = re.sub(r"([。！？])[，、]+", r"\1", text)
    # "三步走：。" 这种"冒号紧跟句号"念起来会多一次空停顿
    text = re.sub(r"[：:][。！？]", "。", text)
    text = re.sub(r"[。！？]{2,}", "。", text)
    text = re.sub(r"(?m)^[，。！？\s]+", "", text)
    return text


def _cut_at_sentence(text, limit):
    """按句子边界截断：宁可少念一句，也不要在半个词上断。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    best = -1
    for mark in "。！？!?":
        idx = head.rfind(mark)
        if idx > best:
            best = idx
    if best >= int(limit * 0.3):
        return head[:best + 1]
    return head.rstrip("，、;；:：") + "。"


def naturalize(text, limit=500):
    """返回可以直接交给 TTS 的"人话"；空/全是符号时返回 ""。"""
    body = str(text or "")
    if not body.strip():
        return ""
    body = _RE_CODE_BLOCK.sub("。", body)
    body = _RE_MD_LINK.sub(r"\1", body)
    body = _RE_URL.sub("", body)
    body = _RE_INLINE_CODE.sub(r"\1", body)
    body = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2) or "", body)
    body = _RE_UNDER_CJK.sub("", body)
    body = _RE_HEADING.sub("", body)
    body = _RE_QUOTE.sub("", body)
    body = _RE_NUM_BULLET.sub("", body)
    body = _RE_BULLET.sub("", body)
    body = _RE_STARS.sub("", body)
    # emoji 本来就是"停顿一下"，直接删会把两句粘成一句（"搞定啦三步走"），
    # 换成逗号更接近人说话的换气
    body = _RE_EMOJI.sub("，", body)
    # 换行 = 换气：做成句号，比一口气念完自然
    body = re.sub(r"\r\n?|\n", "。", body)
    body = re.sub(r"[ \t\u3000]+", " ", body)
    body = re.sub(r"(?<=[%s]) +(?=[%s])" % (_CJK, _CJK), "", body)
    # 标点两侧的空格对朗读没意义（"搞定啦 ， 三步走" 会变成奇怪的停顿）
    body = re.sub(r" +([，。！？、；：])", r"\1", body)
    body = re.sub(r"([，。！？、；：]) +", r"\1", body)
    body = _tidy_punct(body).strip()
    body = re.sub(r"^[，。！？、;；:：]+", "", body).strip()
    if not body:
        return ""
    body = _cut_at_sentence(body, max(20, int(limit)))
    body = body.rstrip("，、;；:： ")
    if body and body[-1] not in _END_PUNCT:
        body += "。"
    return body
