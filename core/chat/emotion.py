# -*- coding: utf-8 -*-
"""轻量情绪状态机（批次 D5）。

用户文本 → ``valence(-1..1)`` + ``tags`` + 一句建议语气 ``voice``；
``next_state`` 做按键转移与时间衰减，``voice_hint`` 生成可直接拼进人格提示的短句。
纯规则、无模型、无落盘，坏输入一律降级为中性。
"""
from __future__ import annotations

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover - 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

POSITIVE = ("开心", "高兴", "太好了", "谢谢", "喜欢", "棒", "爽", "成功",
            "搞定", "哈哈", "笑死", "么么", "爱你", "赞")
NEGATIVE = ("难过", "郁闷", "烦", "崩", "累", "难受", "焦虑", "害怕",
            "生气", "讨厌", "失败", "不行", "糟糕", "委屈", "哭")
HELP = ("怎么办", "帮我", "救命", "不会", "不懂", "求助", "卡住", "怎么弄")
SURPRISE = ("没想到", "居然", "竟然", "惊", "哇", "天呐", "牛")

VOICES = {
    "positive": "语气轻快，可以带一点笑意，别过度热情。",
    "negative": "先接住情绪，语气温和，别急着讲道理。",
    "help": "语气耐心、直接给办法，少寒暄。",
    "surprise": "可以带点惊讶，顺着对方的情绪接一句。",
    "neutral": "",
}

# 语气优先级：求助 > 负面 > 惊喜 > 正面
_PRIORITY = ("help", "negative", "surprise", "positive")


def derive(text):
    """从单句推情绪：返回 ``{valence, tags, voice}``。"""
    low = str(text or "").lower()
    tags = []
    if any(w in low for w in NEGATIVE):
        tags.append("negative")
    if any(w in low for w in POSITIVE):
        tags.append("positive")
    if any(w in low for w in HELP):
        tags.append("help")
    if any(w in low for w in SURPRISE):
        tags.append("surprise")
    valence = 0.0
    if "positive" in tags:
        valence += 0.6
    if "negative" in tags:
        valence -= 0.7
    valence = max(-1.0, min(1.0, valence))
    voice = VOICES["neutral"]
    for tag in _PRIORITY:
        if tag in tags:
            voice = VOICES[tag]
            break
    return {"valence": round(valence, 2), "tags": tags, "voice": voice}


def next_state(cur, text, *, decay=0.5):
    """按键转移：有新情绪就覆盖，否则沿用并按 ``decay`` 衰减到中性。"""
    try:
        got = derive(text)
        if got["tags"]:
            return got
        prev = dict(cur or {})
        value = float(prev.get("valence", 0.0)) * decay
        if abs(value) < 0.1:
            return {"valence": 0.0, "tags": [], "voice": ""}
        out = dict(prev)
        out["valence"] = round(value, 2)
        return out
    except Exception as e:
        _x6_swallowed(__name__, e, "next_state")
        return {}


def voice_hint(state):
    """把状态转成一句可注入人格的短提示；无情绪返回空。"""
    try:
        state = dict(state or {})
        if not state.get("tags"):
            return ""
        voice = str(state.get("voice") or "").strip()
        return "本轮语气：" + voice if voice else ""
    except Exception as e:
        _x6_swallowed(__name__, e, "voice_hint")
        return ""
