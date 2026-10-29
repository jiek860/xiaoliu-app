# -*- coding: utf-8 -*-
"""记忆 v2 统一入口（批次 43.1）。

现有记忆资产各管一段（记忆卡 / 情景 / 向量 / 遗忘曲线），本模块只做三件事：
统一卡片 schema、统一召回排序、统一注入预算。数据仍读旧的
``data/memory_cards.jsonl``，不迁移、不改写。

排序权重按 docs/102 §2.9：
    0.45 相关度 + 0.25 重要度 + 0.20 时新性（半衰期 60 天）+ 0.10 话题匹配

默认开关 ``记忆.v2`` = ``shadow``：只记录「本来会注入什么」，不改上下文；
``on`` 才真正替换旧的记忆段；``off`` 完全走旧入口。任何异常都回落旧入口。
"""
import hashlib
import json
import math
import os
import re
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

DEFAULT_LIMIT = 3
DEFAULT_CHARS = 200
DEFAULT_HOURS = 24
HALF_LIFE_DAYS = 60.0
WEIGHTS = (0.45, 0.25, 0.20, 0.10)

_TYPES = ("fact", "preference", "event", "commitment", "relationship")
_TYPE_IMPORTANCE = {
    "fact": 0.60, "preference": 0.80, "event": 0.55,
    "commitment": 0.90, "relationship": 0.75,
}
_TYPE_RULES = (
    ("commitment", ("答应", "承诺", "提醒我", "别忘了", "以后", "下次")),
    ("preference", ("喜欢", "讨厌", "偏好", "不爱", "习惯")),
    ("relationship", ("朋友", "家人", "爸妈", "对象", "孩子", "同事", "老板")),
    ("event", ("计划", "打算", "准备", "周末", "明天", "考试", "旅行")),
)
_TOPIC_WORDS = {
    "代码": ("代码", "报错", "函数", "bug", "python", "项目"),
    "情绪": ("情绪", "累", "焦虑", "烦", "难过", "压力"),
    "工作": ("工作", "上班", "加班", "周报", "汇报", "公司"),
    "生活": ("生活", "周末", "吃饭", "睡觉", "天气", "电影"),
}
_LINE_PREFIX = "【记忆】"
_LINE_BODY = 56


def clean(text):
    """压掉换行与连续空白，记忆行必须是一行。"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def grams(text):
    """字符 bigram 集合：中文按字、英文数字按词内片段。"""
    t = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").lower())
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def relevance(query, text):
    """查询与卡片的相关度 0..1（查询 bigram 被覆盖的比例）。"""
    q = grams(query)
    if not q:
        return 0.0
    return len(q & grams(text)) / float(len(q))


def infer_type(text):
    t = str(text or "")
    for name, words in _TYPE_RULES:
        if any(w in t for w in words):
            return name
    return "fact"


def infer_topic(text):
    t = str(text or "")
    for name, words in _TOPIC_WORDS.items():
        if any(w in t for w in words):
            return name
    return ""


def infer_importance(text, ctype):
    val = _TYPE_IMPORTANCE.get(ctype, 0.60)
    if "记住" in str(text or "") or "重要" in str(text or ""):
        val += 0.10
    return max(0.0, min(1.0, val))


def card_id(text):
    return "m_" + hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:10]


def recency(created_at, now):
    """半衰期 60 天的时新性；未来时间按 1.0 处理。"""
    age = max(0.0, float(now) - float(created_at)) / 86400.0
    return math.pow(0.5, age / HALF_LIFE_DAYS)


def normalize(raw, *, now=None, index=0):
    """把旧卡（facts/date/time）或新卡统一成 v2 schema；无效返回 None。"""
    try:
        if not isinstance(raw, dict):
            return None
        facts = [clean(f) for f in (raw.get("facts") or []) if clean(f)]
        text = clean(raw.get("text") or "；".join(facts[:3]))
        if not text:
            return None
        ctype = str(raw.get("type") or "")
        if ctype not in _TYPES:
            ctype = infer_type(text)
        created = float(raw.get("created_at") or raw.get("time") or 0)
        if created <= 0:
            created = float(now or time.time()) - index * 60.0
        try:
            importance = float(raw.get("importance"))
        except (TypeError, ValueError):
            importance = infer_importance(text, ctype)
        card = {
            "id": str(raw.get("id") or card_id(text)),
            "type": ctype,
            "text": text,
            "subject": str(raw.get("subject") or "user"),
            "confidence": _num(raw.get("confidence"), 0.80),
            "importance": max(0.0, min(1.0, importance)),
            "created_at": created,
            "last_used_at": _num(raw.get("last_used_at"), 0.0),
            "source": str(raw.get("source") or "chat"),
            "expires_at": None,
            "conflicts_with": list(raw.get("conflicts_with") or []),
        }
        topic = str(raw.get("topic") or infer_topic(text))
        if topic:
            card["topic"] = topic
        if raw.get("follow_up"):
            card["follow_up"] = clean(raw["follow_up"])
        if raw.get("expires_at") is not None:
            card["expires_at"] = float(raw["expires_at"])
        return card
    except (TypeError, ValueError, AttributeError):
        return None


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def load_cards(path, *, now=None, limit=200):
    """读 jsonl，坏的整行跳过；同 id 保留最后一条（新覆盖旧）。"""
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fp:
            lines = fp.readlines()[-max(1, int(limit or 200)):]
    except (OSError, ValueError):
        return rows
    by_id = {}
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except (ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "bad_card_line")
            continue
        card = normalize(raw, now=now, index=index)
        if card:
            by_id[card["id"]] = card
    rows.extend(by_id.values())
    return rows


def score(card, query, topic, now):
    """返回 (综合分, 相关度, 话题命中)；权重见 docs/102 §2.9。"""
    rel = relevance(query, card.get("text", ""))
    own_topic = card.get("topic", "")
    topic_hit = 0.0
    if topic and (own_topic == topic
                  or any(w in card.get("text", "") for w in _TOPIC_WORDS.get(topic, ()))):
        topic_hit = 1.0
    rec = recency(card.get("created_at", 0), now)
    value = (WEIGHTS[0] * rel + WEIGHTS[1] * card.get("importance", 0.6)
             + WEIGHTS[2] * rec + WEIGHTS[3] * topic_hit)
    return round(value, 4), rel, topic_hit


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict) and isinstance(data.get("injected"), dict):
            return data
    except (OSError, ValueError, TypeError) as e:
        _x6_swallowed(__name__, e, "load_state")
    return {"version": 2, "injected": {}}


def save_state(path, state):
    """原子写；失败只静默，绝不影响回复。"""
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(state, fp, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        _x6_swallowed(__name__, e, "save_state")
        return False


def recently_injected(state, cid, now, hours):
    try:
        last = float((state.get("injected") or {}).get(cid) or 0)
    except (TypeError, ValueError):
        return False
    return last > 0 and (float(now) - last) < max(0.0, float(hours)) * 3600


class MemoryV2:
    def __init__(self, base="."):
        self.base = str(base or ".")
        self.path = os.path.join(self.base, "data", "memory_cards.jsonl")
        self.state_path = os.path.join(self.base, "data", "memory_v2_state.json")

    def recall(self, query, *, topic="", limit=DEFAULT_LIMIT,
               max_chars=DEFAULT_CHARS, hours=DEFAULT_HOURS, now=None):
        """召回不超过 limit 张、总长不超过 max_chars 的卡（不改状态）。"""
        now = float(now or time.time())
        self.last_scores = []
        state = load_state(self.state_path)
        ranked = []
        for card in load_cards(self.path, now=now):
            expires = card.get("expires_at")
            if expires is not None and expires <= now:
                continue
            if recently_injected(state, card["id"], now, hours):
                continue
            value, rel, topic_hit = score(card, query, topic, now)
            self.last_scores.append((card["id"], value))
            if rel <= 0 and topic_hit <= 0:
                continue                 # 不相关的不硬塞
            ranked.append((value, card))
        ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
        picked, lines, total = [], [], 0
        for _value, card in ranked:
            if len(picked) >= max(0, int(limit or 0)):
                break
            line = self.line(card)
            cost = len(line) + (1 if lines else 0)
            if total + cost > max(0, int(max_chars or 0)):
                if not lines:
                    break
                continue
            picked.append(card)
            lines.append(line)
            total += cost
        return picked

    def commit(self, cards, *, now=None):
        """记录本次真正注入的卡；24 小时内不再重复注入。"""
        if not cards:
            return False
        now = float(now or time.time())
        state = load_state(self.state_path)
        injected = state.setdefault("injected", {})
        for card in cards:
            injected[str(card.get("id") or "")] = now
        if len(injected) > 500:              # 只留最近的 500 条
            keep = sorted(injected.items(), key=lambda item: item[1])[-500:]
            state["injected"] = dict(keep)
        return save_state(self.state_path, state)

    @staticmethod
    def line(card):
        text = clean(card.get("text") or "")
        if len(text) > _LINE_BODY:
            text = text[:_LINE_BODY - 1] + "…"
        return _LINE_PREFIX + text

    def render(self, cards):
        return "\n".join(self.line(card) for card in (cards or []))
