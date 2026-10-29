# -*- coding: utf-8 -*-
"""分层人格卡（批次 42.4）。

L1 身份 / L2 风格 / L3 场景 / L4 对用户的了解，种子放在
``core/chat/data/persona_tiers.json``（随包发布）；用户可在
``data/persona_tiers.json`` 放同名文件覆盖。运行时只拼当前需要的层，
默认总长 ≤ 520 字，避免「人格 500 字 + 案例 + 历史」把模型压成长篇。

开关 ``聊天.人格卡`` = ``off | shadow | on``，默认 ``shadow``：
shadow 只构建并记录（`PromptAssembler.last_persona`），仍用旧人格；
``on`` 才真正替换系统提示词。风格由 ``聊天.人格风格`` 选择，缺省用卡片默认值。
"""
import json
import os

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "persona_tiers.json")

_DEFAULT = {
    "version": "builtin",
    "default_style": "松弛",
    "max_chars": 520,
    "layers": {
        "l1": {"text": "你是小6，住在用户电脑里的AI朋友。说话像熟人：先接住问题，再给结论。"},
        "l2": {"styles": {"松弛": {"text": "语气松弛，短句为主。", "emoji_budget": 2}}},
        "l3": {"topics": {}},
        "l4": {"template": ""},
    },
    "banned": {"作为AI": "我", "希望对你有所帮助": ""},
}
_CACHE = {}


def _read(path):
    try:
        stat = os.stat(path)
        hit = _CACHE.get(path)
        if hit and hit[0] == stat.st_mtime:
            return hit[1]
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        _CACHE[path] = (stat.st_mtime, data)
        return data
    except (OSError, ValueError, TypeError):
        return None


def _card(data):
    base = json.loads(json.dumps(_DEFAULT))
    if not isinstance(data, dict):
        return base
    for key in ("version", "default_style", "max_chars"):
        if key in data:
            base[key] = data[key]
    layers = data.get("layers") or {}
    for key in ("l1", "l2", "l3", "l4"):
        if isinstance(layers.get(key), dict):
            base["layers"][key].update(layers[key])
    if isinstance(data.get("banned"), dict):
        base["banned"].update(data["banned"])
    return base


class PersonaCard:
    def __init__(self, base=".", data=None, path=""):
        self.base = str(base or ".")
        self.path = path or os.path.join(self.base, "data", "persona_tiers.json")
        if data is None:
            data = _read(self.path)
        if data is None and os.path.abspath(self.path) != _SEED_PATH:
            data = _read(_SEED_PATH)   # 用户没放覆盖文件时用随包种子
        self.data = _card(data)

    @classmethod
    def load(cls, base=".") -> "PersonaCard":
        return cls(base=base)

    @property
    def version(self):
        return str(self.data.get("version") or "")

    def style_names(self):
        return list((self.data["layers"]["l2"].get("styles") or {}).keys())

    def banned_pairs(self):
        return [(str(k), str(v)) for k, v in (self.data.get("banned") or {}).items()]

    def banned_words(self):
        return [k for k, _ in self.banned_pairs()]

    def emoji_budget(self, style=None):
        try:
            styles = self.data["layers"]["l2"].get("styles") or {}
            name = str(style or self.data.get("default_style") or "")
            row = styles.get(name) or {}
            return int(row.get("emoji_budget", 2))
        except (TypeError, ValueError, AttributeError):
            return 2

    def build(self, *, style=None, state=None, plan=None, user_name="", prefs=()) -> dict:
        try:
            return self._build(style, state or {}, plan or {}, user_name, prefs)
        except Exception as e:
            _x6_swallowed(__name__, e, "card_build")
            return {"text": _DEFAULT["layers"]["l1"]["text"], "style": "松弛",
                    "version": self.version, "emoji_budget": 2, "chars": 0,
                    "banned_count": len(self.banned_pairs()), "layers": ["l1"]}

    def _build(self, style, state, plan, user_name, prefs):
        layers = self.data["layers"]
        styles = layers["l2"].get("styles") or {}
        name = str(style or self.data.get("default_style") or "")
        if name not in styles:
            name = next(iter(styles), "") or "松弛"
        style_row = styles.get(name) or {}
        parts, used = [], ["l1"]
        if layers["l1"].get("text"):
            parts.append(str(layers["l1"]["text"]))
        if style_row.get("text"):
            parts.append(str(style_row["text"]))
            used.append("l2")
        topics = layers["l3"].get("topics") or {}
        topic = str(state.get("topic") or "")
        if topic in topics:
            parts.append(str(topics[topic]))
            used.append("l3")
        if plan.get("act") == "comfort" and "情绪" in topics and topic != "情绪":
            parts.append(str(topics["情绪"]))
            if "l3" not in used:
                used.append("l3")
        rows = [str(x) for x in (prefs or []) if str(x).strip()][:3]
        template = str(layers["l4"].get("template") or "")
        if template and (user_name or rows):
            parts.append(template.format(name=user_name or "你", prefs="；".join(rows)))
            used.append("l4")
        text = "\n".join(parts)
        text = self._cap(text)
        return {"text": text, "style": name, "version": self.version,
                "emoji_budget": int(style_row.get("emoji_budget", 2)),
                "chars": len(text), "banned_count": len(self.banned_pairs()),
                "layers": used}

    def _cap(self, text):
        limit = int(self.data.get("max_chars") or 520)
        if len(text) <= limit:
            return text
        cut = text[:limit]
        pos = max(cut.rfind("。"), cut.rfind("\n"))
        return (cut[:pos + 1] if pos > limit * 0.6 else cut).rstrip()
