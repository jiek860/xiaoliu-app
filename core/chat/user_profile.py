# -*- coding: utf-8 -*-
"""用户画像（批次 O2）：称呼 + 语气偏好，供人格卡 L4 使用。

读写闭环
--------
写：用户在聊天里说「叫我小王 / 我叫… / 你可以叫我…」时，
``personality.learn_user_name()`` 调 ``name_from_text()`` 把称呼落到
``data/personality.json``；语气偏好则沿用记忆卡（「偏好:」事实）自动积累。
读：``PromptAssembler._compose_persona()`` 调 ``collect()``，把称呼和
偏好填进 L4 模板（``core/chat/data/persona_tiers.json`` 的 ``l4.template``）。

为什么单独一个模块
------------------
人格卡只管拼文案，人格引擎只管自己的 json；两边都去扫记忆卡会各写一遍
解析规则。这里把「从哪读、怎么去重」收在一处，读不到就返回空，
绝不让画像读取失败拖垮一轮回复。
"""
import json
import os
import re

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

MAX_PREFS = 4
MAX_NAME = 8
_PREF_PREFIX = "偏好:"
_NICK_PAT = re.compile(
    r"(?:叫我|喊我|我叫|你可以叫我)\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,8})")
_NAME_CUT = re.compile(r"[，,。.！!？?、；;：:\s]|很|就|是|吧|呀|啊|呢|哦")
_BAD_NAME_CHARS = "了个的地得是在没想要有把被给对和与"
_STYLE_PREFS = {"简短": "说话喜欢简短", "详细": "能接受详细展开"}


def name_from_text(text):
    """从一句话里取用户称呼；没有就返回空串。

    「我叫小王，在杭州上班」→ 小王；「叫我老王吧」→ 老王。
    只认主动告知（叫我/喊我/我叫），不猜「我叫了个外卖」这种句子。
    """
    for match in _NICK_PAT.finditer(str(text or "")):
        name = _NAME_CUT.split(match.group(1))[0].strip()
        if not name or name in ("什么", "一下", "名字"):
            continue
        if any(ch in _BAD_NAME_CHARS for ch in name):
            continue
        return name[:MAX_NAME]
    return ""


def _clean_pref(value):
    """把一条偏好压成适合塞进 L4 的短句。"""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.strip("，,。.！!？?、；;：:")
    if text.startswith("我"):
        text = text[1:].strip()
    return text[:24]


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _recent_cards(base, limit=200):
    """读最近 limit 行记忆卡；坏行跳过，返回 dict 列表。"""
    path = os.path.join(str(base or "."), "data", "memory_cards.jsonl")
    try:
        with open(path, encoding="utf-8") as fp:
            lines = [ln for ln in fp.read().splitlines() if ln.strip()][-limit:]
    except OSError:
        return []
    cards = []
    for line in lines:
        try:
            card = json.loads(line)
        except (ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "bad_card")
            continue
        if isinstance(card, dict):
            cards.append(card)
    return cards


def _card_texts(card):
    out = []
    text = str(card.get("text") or "").strip()
    if text:
        out.append(text)
    for fact in card.get("facts") or []:
        fact = str(fact or "").strip()
        if fact:
            out.append(fact)
    return out


def _prefs_of(text):
    """从「偏好:喜欢短句；计划:…」这样的行里挑出偏好。"""
    out = []
    for part in re.split(r"[；;\n]", str(text or "")):
        part = part.strip()
        if not part.startswith(_PREF_PREFIX):
            continue
        value = _clean_pref(part[len(_PREF_PREFIX):])
        if value:
            out.append(value)
    return out


def collect(trunk=None, base=None, limit=200):
    """汇总用户画像：{"name": 称呼, "prefs": [偏好…], "style": 语气风格}。"""
    base = str(base or getattr(trunk, "base", ".") or ".")
    config = getattr(trunk, "config", None) or {}
    name = str(config.get("user_name") or "").strip()
    prefs = []
    for row in (config.get("user_prefs") or ()):
        value = _clean_pref(row)
        if value and value not in prefs:
            prefs.append(value)

    personality = _read_json(os.path.join(base, "data", "personality.json"))
    name = name or str(personality.get("user_name") or "").strip()
    style = str(personality.get("user_style") or "").strip()

    # 记忆卡从新到旧：称呼先看最近的，偏好也优先保留最近的
    for card in reversed(_recent_cards(base, limit)):
        for text in _card_texts(card):
            if not name:
                name = name_from_text(text)
            for value in _prefs_of(text):
                if value not in prefs:
                    prefs.append(value)

    style_pref = _STYLE_PREFS.get(style, "")
    if style_pref and style_pref not in prefs:
        prefs.append(style_pref)

    return {"name": name[:MAX_NAME], "prefs": prefs[:MAX_PREFS], "style": style}
