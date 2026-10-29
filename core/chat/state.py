# -*- coding: utf-8 -*-
"""对话状态层 DialogueState（批次 42.1）。

把「靠提示词暗示」变成「显式状态」：意图、期望、长度、情绪、话题、承诺
都落成可持久化、可回放、可测试的字段。

约束：只做规则更新、不调模型；单文件原子写；损坏/缺失回默认值；
任何异常都不冒泡（diagnostics.swallowed）；不 import core.pipeline 避免循环依赖。
开关 ``chat.state = off | shadow | on``，默认 shadow：照常更新落盘，
但回复链路不读取（零行为差异），供 42.2 规划器灰度。
"""
import json
import os
import threading
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover - 单独跑本文件时的兜底
    def _x6_swallowed(component, error, context=""):
        return None

_SCHEMA_VERSION = 1
_SAVE_LOCK = threading.Lock()
_MAX_TEXT = 80

# 顺序即优先级：纠错 > 情绪 > 事实提问 > 求助 > 玩笑 > 寒暄
_INTENT_RULES = (
    ("correct", ("不对", "不是这个", "我是说", "你错了", "理解错", "跑题", "我不是", "重新说")),
    ("vent", ("烦", "累", "难受", "崩溃", "气死", "焦虑", "睡不着", "郁闷", "压力大", "不想上班")),
    ("ask_fact", ("是什么", "为什么", "怎么", "多少", "几点", "谁", "哪", "能不能", "可以吗")),
    ("request_help", ("帮我", "帮忙", "写", "做", "修", "改", "查", "看看", "优化", "实现")),
    ("play", ("讲个笑话", "逗我", "来点", "陪我聊", "无聊")),
    ("smalltalk", ("你好", "在吗", "hi", "hello", "谢谢", "晚安", "早", "早安", "哈哈")),
)
_TOPIC_RULES = (
    ("代码", ("代码", "报错", "函数", "bug", "pytest", "重构", "接口", "编译", "文件", "日志")),
    ("情绪", ("累", "烦", "难受", "焦虑", "开心", "被夸", "郁闷", "压力")),
    ("工作", ("上班", "老板", "项目", "周报", "加班", "同事", "会议")),
    ("生活", ("天气", "吃", "睡", "周末", "电影", "游戏", "旅行", "健身")),
)
_POSITIVE = ("开心", "高兴", "谢谢", "喜欢", "不错", "成功", "搞定", "太好了", "舒服", "哈哈", "爽")
_NEGATIVE = ("烦", "累", "难受", "崩溃", "气死", "焦虑", "睡不着", "失败", "糟糕", "讨厌", "郁闷",
             "压力", "委屈")
_COMMIT_TIME = ("明天", "后天", "今晚", "稍后", "待会", "下周", "周一", "周二", "周三", "周四",
                "周五", "周六", "周日")
_COMMIT_ACT = ("提醒我", "记得", "记一下", "别忘了", "帮我记")


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _clip(text, limit=_MAX_TEXT):
    return str(text or "").strip()[:limit]


def _blank():
    return {
        "version": _SCHEMA_VERSION, "session_id": "", "updated_at": 0,
        "user": {"name": "", "relation_stage": "stranger", "preferences": [], "dislikes": []},
        "affect": {"user_valence": 0.0, "user_arousal": 0.3, "bot_valence": 0.3,
                   "bot_energy": 0.7, "trust": 0.5, "warmth": 0.5},
        "topic": {"current": "", "recent": [], "switched_at": 0, "streak": 0},
        "turn": {"intent": "chat", "expects": "short_action", "user_brevity": "short",
                 "unanswered": [], "bot_last_acts": []},
        "commitments": [], "open_questions": [], "stats": {"turns": 0, "first_seen": 0},
    }


def _merge_defaults(target, default):
    """把旧文件/缺字段补成当前 schema（只补不删）。"""
    if not isinstance(target, dict):
        return default
    out = dict(default)
    for key, value in target.items():
        base = default.get(key)
        if isinstance(base, dict) and isinstance(value, dict):
            out[key] = _merge_defaults(value, base)
        elif isinstance(base, list) and not isinstance(value, list):
            out[key] = base
        else:
            out[key] = value
    return out


def _sanitize(data):
    blank = _blank()
    data = _merge_defaults(data, blank)
    for key in ("user", "affect", "topic", "turn", "stats"):
        if not isinstance(data.get(key), dict):
            data[key] = dict(blank[key])
    affect = data["affect"]
    affect["user_valence"] = round(_clamp(affect.get("user_valence"), -1, 1), 3)
    for key in ("user_arousal", "bot_valence", "bot_energy", "trust", "warmth"):
        affect[key] = round(_clamp(affect.get(key)), 3)
    stats = data["stats"]
    try:
        stats["turns"] = max(0, int(stats.get("turns") or 0))
    except (TypeError, ValueError):
        stats["turns"] = 0
    topic = data["topic"]
    if not isinstance(topic.get("recent"), list):
        topic["recent"] = []
    topic["recent"] = [_clip(t, 20) for t in topic["recent"]][-5:]
    turn = data["turn"]
    turn["unanswered"] = [_clip(t) for t in turn.get("unanswered") or []][-3:]
    for key in ("commitments", "open_questions"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def classify_intent(text):
    q = str(text or "").lower()
    for name, words in _INTENT_RULES:
        if any(w.lower() in q for w in words):
            return name
    return "chat"


def classify_topic(text):
    q = str(text or "")
    for name, words in _TOPIC_RULES:
        if any(w in q for w in words):
            return name
    return ""


def _expects(intent, text):
    if intent == "vent":
        return "comfort"
    if intent in ("correct", "request_help"):
        return "short_action"
    if intent == "ask_fact":
        return "explanation"
    if any(w in text for w in ("怎么", "为什么", "解释", "区别")):
        return "explanation"
    return "question_back" if ("？" in text or "?" in text) else "short_action"


def _brevity(text):
    n = len(str(text or "").strip())
    return "short" if n <= 8 else ("normal" if n <= 40 else "long")


def _emotion_target(text):
    pos = sum(1 for w in _POSITIVE if w in text)
    neg = sum(1 for w in _NEGATIVE if w in text)
    exclaim = text.count("！") + text.count("!")
    arousal = _clamp(0.3 + 0.12 * exclaim + 0.05 * (text.count("？") + text.count("?")))
    if pos == neg:
        return 0.0, arousal
    return (0.6 if pos > neg else -0.6), max(arousal, 0.5 if neg else 0.45)


def _due_for(text, now):
    from datetime import datetime, timedelta

    t = datetime.fromtimestamp(now)
    if "稍后" in text or "待会" in text:
        return (t + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    day = t.replace(hour=9, minute=0, second=0, microsecond=0)
    if "后天" in text:
        day += timedelta(days=2)
    elif "明天" in text:
        day += timedelta(days=1)
    elif "今晚" in text:
        day = t.replace(hour=20, minute=0, second=0, microsecond=0)
    elif any(w in text for w in ("下周", "周一", "周二")):
        day += timedelta(days=7)
    else:
        return ""
    return day.strftime("%Y-%m-%dT%H:%M")


class DialogueState:
    """单会话对话状态；线程内更新、跨线程原子落盘。"""

    def __init__(self, base=".", data=None, path=""):
        self.base = str(base or ".")
        self.path = path or os.path.join(self.base, "data", "chat_state.json")
        self.data = _sanitize(data or _blank())

    @classmethod
    def load(cls, base=".") -> "DialogueState":
        path = os.path.join(str(base or "."), "data", "chat_state.json")
        raw = {}
        try:
            with open(path, "r", encoding="utf-8") as fp:
                raw = json.load(fp)
        except (OSError, ValueError, TypeError):
            raw = {}
        return cls(base=base, data=raw, path=path)

    def save(self) -> bool:
        try:
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            self.data["updated_at"] = int(time.time())
            tmp = self.path + ".tmp"
            with _SAVE_LOCK:
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(self.data, fp, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            return True
        except Exception as e:
            _x6_swallowed(__name__, e, "state_save")
            try:
                os.remove(self.path + ".tmp")
            except OSError:
                pass
            return False

    def summary(self):
        turn, affect = self.data["turn"], self.data["affect"]
        return {"intent": turn.get("intent", "chat"),
                "expects": turn.get("expects", "short_action"),
                "brevity": turn.get("user_brevity", "short"),
                "topic": self.data["topic"].get("current", ""),
                "relation": self.data["user"].get("relation_stage", "stranger"),
                "valence": affect.get("user_valence", 0.0),
                "arousal": affect.get("user_arousal", 0.3),
                "trust": affect.get("trust", 0.5),
                "unanswered": len(turn.get("unanswered") or []),
                "commitments": len([c for c in self.data["commitments"] if c.get("status") == "open"]),
                "turns": self.data["stats"].get("turns", 0)}

    def update(self, user_text, *, now=None) -> dict:
        try:
            return self._update(str(user_text or ""), float(now or time.time()))
        except Exception as e:
            _x6_swallowed(__name__, e, "state_update")
            return self.summary()

    def _update(self, text, now):
        data = self.data
        if not data.get("session_id"):
            stamp = time.strftime("%Y%m%d", time.localtime(now))
            data["session_id"] = "s_%s_%d" % (stamp, os.getpid())
        stats = data["stats"]
        if not stats.get("first_seen"):
            stats["first_seen"] = int(now)
        stats["turns"] = int(stats.get("turns") or 0) + 1
        intent = classify_intent(text)
        turn = data["turn"]
        turn["intent"] = intent
        turn["expects"] = _expects(intent, text)
        turn["user_brevity"] = _brevity(text)
        mood, arousal = _emotion_target(text)
        affect = data["affect"]
        affect["user_valence"] = round(0.7 * float(affect["user_valence"]) + 0.3 * mood, 3)
        affect["user_arousal"] = round(0.7 * float(affect["user_arousal"]) + 0.3 * arousal, 3)
        affect["trust"] = round(_clamp(float(affect["trust"]) + 0.01, 0, 0.95), 3)
        affect["warmth"] = round(_clamp(float(affect["warmth"]) + (0.03 if intent == "vent" else 0.015)), 3)
        if stats["turns"] >= 30 and affect["trust"] >= 0.65:
            stage = "close"
        elif stats["turns"] >= 8:
            stage = "familiar"
        else:
            stage = "stranger"
        data["user"]["relation_stage"] = stage
        self._update_topic(text, now)
        self._update_questions(text, intent)
        self._update_commitments(text, now)
        self._expire(now)
        return self.summary()

    def _update_topic(self, text, now):
        topic = self.data["topic"]
        candidate = classify_topic(text)
        if not candidate:
            return
        if candidate == topic.get("current"):
            topic["streak"] = 0
            return
        topic["streak"] = int(topic.get("streak") or 0) + 1
        if topic["streak"] < 2 and topic.get("current"):
            return  # 连续 2 轮才切换，避免一句带过就翻篇
        topic["current"] = candidate
        topic["switched_at"] = int(now)
        topic["streak"] = 0
        recent = [t for t in topic.get("recent") or [] if t != candidate]
        recent.append(candidate)
        topic["recent"] = recent[-5:]

    def _update_questions(self, text, intent):
        if intent != "ask_fact" or ("？" not in text and "?" not in text):
            return
        unanswered = self.data["turn"]["unanswered"]
        item = _clip(text, 60)
        if item and item not in unanswered:
            unanswered.append(item)
        del unanswered[:-3]

    def _update_commitments(self, text, now):
        if not any(w in text for w in _COMMIT_ACT) or not any(w in text for w in _COMMIT_TIME):
            return
        item = _clip(text, 60)
        for c in self.data["commitments"]:
            if c.get("text") == item and c.get("status") == "open":
                return
        self.data["commitments"].append(
            {"text": item, "due": _due_for(text, now), "status": "open", "created_at": int(now)})
        del self.data["commitments"][:-20]

    def _expire(self, now):
        from datetime import datetime

        for c in self.data["commitments"]:
            if c.get("status") != "open" or not c.get("due"):
                continue
            try:
                due = datetime.strptime(c["due"], "%Y-%m-%dT%H:%M").timestamp()
            except ValueError:
                continue
            if due < now:
                c["status"] = "overdue"
