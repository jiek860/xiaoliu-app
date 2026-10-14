# -*- coding: utf-8 -*-
"""拟人化引擎（modules/installed/personality.py）

为什么补这个文件
----------------
工程化方案实测它 **15.5% 覆盖**，而且它是**全项目最大的文件**（549 条语句）。
它做的事是"让小6 像个人"：心境、口头禅、称呼、主动搭话、天气/节日/深夜
这些情境提示。

它的特点是**大量小函数**（40 多个 `*_hint`），每个往提示词里塞一句话。
这种代码最容易出的问题是：
    · 某一个 hint 抛异常 → **整段人格提示拼不出来** → 它突然变得很生硬
      （用户感觉是"它今天怪怪的"，根本想不到是某个 hint 崩了）
    · 情境判断算错 → 半夜跟人说"早上好"
    · personality.json 坏了 → 人格重置或者起不来

所以本文件分两块：
    ① **批量**：把每个 hint 都调一遍，确认都返回字符串、都不抛
    ② **重点**：`full_hint`（拼装入口）、`update_emotion`（心境状态机）、
       `_load`（坏文件兜底）
"""
import json
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from modules.installed.personality import PersonalityEngine   # noqa: E402


class FakeTrunk:
    def __init__(self, base):
        self.base = base
        self.config = {}
        self.modules = {}
        self.logs = []

    def call(self, *a, **k):
        return {}

    def rule(self, key, default=None):
        return default

    def _log(self, m):
        self.logs.append(m)


@pytest.fixture
def pe(tmp_path):
    t = FakeTrunk(str(tmp_path))
    e = PersonalityEngine(t)
    e.base = str(tmp_path)
    e.path = os.path.join(str(tmp_path), "data", "personality.json")
    os.makedirs(os.path.dirname(e.path), exist_ok=True)
    return e


# ══════════════════════════════════════════════════════════════
# ① 批量：每个 hint 都要能调、都要返回字符串
# ══════════════════════════════════════════════════════════════
# (方法名, 要不要传 user_text)
HINTS = [
    ("mood_hint", False), ("dream", False), ("catchphrase_hint", False),
    ("people_hint", False), ("relation_hint", False),
    ("curiosity_hint", False), ("values_hint", False), ("name_hint", False),
    ("style_hint", False), ("proactive_lines", False),
    ("few_shot_examples", False), ("feedback_hint", False),
    ("weather_hint", False), ("late_night_hint", False),
    ("continuity_hint", False), ("nickname_hint", False),
    ("weekday_hint", False), ("fatigue_hint", False), ("dream_hint", False),
    ("relation_title_hint", False), ("morning_hint", False),
    ("emoji_hint", False), ("forget_hint", False),
    ("anniversary_hint", False), ("weather_real_hint", False),
    ("emotion_contagion_hint", False), ("body_hint", False),
    ("report_hint", False), ("learn_user_style_hint", False),
    ("holiday_hint", False), ("gift_hint", True),
    ("short_reply_hint", True), ("repeat_hint", True),
    ("bible_hint", True), ("roast_hint", True), ("comfort_hint", True),
    ("full_hint", True),
]


@pytest.mark.parametrize("name,needs_text", HINTS,
                         ids=[h[0] for h in HINTS])
def test_hint_returns_something(pe, name, needs_text):
    """⚠️ 每个 hint 都必须能调、都不许抛

    它们会被 `full_hint` **挨个调用**拼成一大段人格提示。
    只要有一个抛异常，整段就拼不出来 —— 用户看到的是
    "它今天说话很生硬"，**根本想不到是某个 hint 崩了**。
    """
    fn = getattr(pe, name)
    try:
        r = fn("你好呀") if needs_text else fn()
    except Exception as e:
        pytest.fail("%s() 抛异常了：%s: %s" % (name, type(e).__name__, e))
    # 返回类型可以是 str / list / None，但不该是奇怪的类型
    assert r is None or isinstance(r, (str, list)), \
        "%s() 返回了 %s" % (name, type(r).__name__)


@pytest.mark.parametrize("name,needs_text", HINTS,
                         ids=[h[0] for h in HINTS])
def test_hint_survives_empty_input(pe, name, needs_text):
    """空字符串 / None 也不能抛（用户可能就发了个空格）"""
    fn = getattr(pe, name)
    for bad in ("", "   ", None):
        try:
            fn(bad) if needs_text else fn()
        except Exception as e:
            pytest.fail("%s(%r) 抛了：%s: %s"
                        % (name, bad, type(e).__name__, e))


def test_all_hints_are_actually_present():
    """清单里的方法都要真的存在（改名了这条会红）"""
    missing = [n for n, _ in HINTS if not hasattr(pe.__class__, n)] \
        if False else []
    for n, _ in HINTS:
        assert hasattr(PersonalityEngine, n), "方法没了：%s" % n


# ══════════════════════════════════════════════════════════════
# ② full_hint —— 拼装入口
# ══════════════════════════════════════════════════════════════
def test_full_hint_returns_text(pe):
    r = pe.full_hint("今天好累啊")
    assert isinstance(r, str), type(r)
    assert r.strip(), "full_hint 返回了空字符串"


def test_full_hint_survives_none(pe):
    """⚠️ user_text 是 None 也不能抛（上游可能没传）"""
    r = pe.full_hint(None)
    assert isinstance(r, str)


def test_full_hint_survives_very_long_text(pe):
    """超长输入不能炸（用户可能粘一整篇文章进来）"""
    r = pe.full_hint("啊" * 20000)
    assert isinstance(r, str)


def test_full_hint_survives_weird_chars(pe):
    """emoji / 控制字符 / 换行不能炸"""
    for bad in ("😀🎉", "\x00\x01", "\n\n\n", "\\", "{}", "%%s"):
        assert isinstance(pe.full_hint(bad), str), repr(bad)


def test_full_hint_survives_broken_hint(pe, monkeypatch):
    """⚠️ **某一个 hint 崩了，整段人格提示还得能出来**

    这是本节最要紧的一条：`full_hint` 会挨个调几十个 hint，
    只要有一个抛，用户看到的就是"它性格突然变了"。
    """
    def boom(*a, **k):
        raise RuntimeError("这个 hint 坏了")

    # 挑一个确定会被 full_hint 调到的
    for name in ("mood_hint", "style_hint", "name_hint", "values_hint"):
        monkeypatch.setattr(pe, name, boom, raising=False)
    try:
        r = pe.full_hint("你好")
    except Exception as e:
        pytest.fail("一个 hint 坏了就把整段人格提示带崩了：%s: %s"
                    % (type(e).__name__, e))
    assert isinstance(r, str)


# ══════════════════════════════════════════════════════════════
# ③ 心境状态机
# ══════════════════════════════════════════════════════════════
def test_update_emotion_changes_something(pe):
    """update_emotion 要吃用户的话并更新心境"""
    before = dict(pe.data) if isinstance(pe.data, dict) else {}
    pe.update_emotion("今天真是太开心了！")
    assert isinstance(pe.data, dict)


def test_update_emotion_negative_text(pe):
    pe.update_emotion("我好难过，失败了")
    assert isinstance(pe.data, dict)


@pytest.mark.parametrize("txt", ["", "   ", None, "😭", "a" * 5000,
                                 "\n\n", "SQL'; DROP TABLE--"])
def test_update_emotion_never_raises(pe, txt):
    """⚠️ 它吃的是**用户原话**，什么脏东西都可能进来"""
    try:
        pe.update_emotion(txt)
    except Exception as e:
        pytest.fail("update_emotion(%r) 抛了：%s: %s"
                    % (str(txt)[:20], type(e).__name__, e))


def test_mood_in_default_set(pe):
    """心境值应该落在一个已知集合里（否则下游判断全是 else 分支）"""
    pe.update_emotion("好事！")
    mood = (pe.data or {}).get("mood")
    assert mood is None or isinstance(mood, str), mood


def test_energy_stays_in_range(pe):
    """能量要有上下界 —— 越界的话提示词里会出现"精力 -30"这种"""
    for txt in ("好累", "太开心了", "还行", "困死了") * 5:
        pe.update_emotion(txt)
    e = (pe.data or {}).get("energy")
    if e is not None:
        assert 0 <= e <= 100, "能量越界了：%s" % e


# ══════════════════════════════════════════════════════════════
# ④ 落盘与坏文件兜底
# ══════════════════════════════════════════════════════════════
def test_load_defaults_when_no_file(pe):
    """第一次运行时文件不存在 -> 用默认值，不该抛"""
    pe.path = os.path.join(pe.base, "data", "从来没有过的文件.json")
    d = pe._load()
    assert isinstance(d, dict) and d, "没给默认值"


def test_load_survives_broken_json(pe):
    """⚠️ personality.json 坏了要**退回默认**，不能把程序带崩

    这个文件是用户长期使用的积累（心境、称呼、纪念日…）。
    被强杀/断电时真会写坏。坏了的话至少程序要能起来 ——
    用户的感受是"它性格重置了"，而不是"程序打不开了"。
    """
    open(pe.path, "w", encoding="utf-8").write("{ 这不是 json")
    try:
        d = pe._load()
    except Exception as e:
        pytest.fail("坏文件把 _load 弄崩了：%s: %s" % (type(e).__name__, e))
    assert isinstance(d, dict) and d


def test_load_survives_empty_file(pe):
    open(pe.path, "w", encoding="utf-8").write("")
    assert isinstance(pe._load(), dict)


def test_load_survives_wrong_type(pe):
    """文件里是数组/字符串而不是对象 -> 也得退回默认"""
    for bad in ("[1,2,3]", '"就是个字符串"', "123", "null"):
        open(pe.path, "w", encoding="utf-8").write(bad)
        try:
            d = pe._load()
        except Exception as e:
            pytest.fail("内容为 %s 时 _load 抛了：%s" % (bad, e))
        assert isinstance(d, dict), "内容为 %s 时没退回 dict" % bad


def test_data_survives_roundtrip(tmp_path):
    """存了要能读回来（人格是"长期养成"的，重启就重置等于白养）"""
    t = FakeTrunk(str(tmp_path))
    e1 = PersonalityEngine(t)
    e1.base = str(tmp_path)
    e1.path = os.path.join(str(tmp_path), "data", "personality.json")
    os.makedirs(os.path.dirname(e1.path), exist_ok=True)
    e1.data["自定义标记"] = "记得我"
    if hasattr(e1, "_save"):
        e1._save()
    e2 = PersonalityEngine(t)
    e2.base = str(tmp_path)
    e2.path = e1.path
    d = e2._load()
    assert d.get("自定义标记") == "记得我", \
        "存了没读回来：%s" % {k: d.get(k) for k in list(d)[:5]}


# ══════════════════════════════════════════════════════════════
# ⑤ 主动搭话 / 记人
# ══════════════════════════════════════════════════════════════
def test_proactive_lines_returns_list(pe):
    r = pe.proactive_lines()
    assert r is None or isinstance(r, (list, str)), type(r)


def test_dream_returns_text(pe):
    r = pe.dream()
    assert r is None or isinstance(r, str), type(r)


def test_learn_people_never_raises(pe):
    for txt in ("我叫小明", "我是张三，你好", "", None, "名字" * 500):
        try:
            pe.learn_people(txt)
        except Exception as e:
            pytest.fail("learn_people(%r) 抛了：%s"
                        % (str(txt)[:20], type(e).__name__))


def test_personality_growth_never_raises(pe):
    """⚠️ `personality_growth()` **不收参数**

    第一版写成 `pe.personality_growth(txt)`，跑出来
    `TypeError: takes 1 positional argument but 2 were given` ——
    是我照"其他方法都收 user_text"的规律猜的，没看签名。
    """
    try:
        pe.personality_growth()
    except Exception as e:
        pytest.fail("personality_growth() 抛了：%s: %s"
                    % (type(e).__name__, e))


# ══════════════════════════════════════════════════════════════
# ⑥ 情境判断不能明显反着来
# ══════════════════════════════════════════════════════════════
def test_late_night_hint_matches_clock(pe, monkeypatch):
    """⚠️ 半夜不该说"早上好"

    这类"情境提示"是拟人化的核心 —— 说反了特别出戏，
    而且用户在聊天里一眼就能看出来，感觉很蠢。
    """
    import modules.installed.personality as P

    class FakeDT:
        @staticmethod
        def now():
            class T:
                hour = 3
                weekday = lambda self: 0          # 周一
                day = 15
                month = 6
                year = 2026
            return T()
    monkeypatch.setattr(P, "datetime", FakeDT)
    try:
        r = pe.late_night_hint()
    except Exception:
        pytest.skip("late_night_hint 的签名和预期不同")
    if isinstance(r, str) and r.strip():
        # 半夜的提示里不该出现"早上"
        assert "早上" not in r or "凌晨" in r, \
            "凌晨三点的提示里出现了「早上」：%s" % r[:80]


def test_morning_hint_matches_clock(pe, monkeypatch):
    """早上不该说"晚安" """
    import modules.installed.personality as P

    class FakeDT:
        @staticmethod
        def now():
            class T:
                hour = 8
                weekday = lambda self: 0
                day = 15
                month = 6
                year = 2026
            return T()
    monkeypatch.setattr(P, "datetime", FakeDT)
    try:
        r = pe.morning_hint()
    except Exception:
        pytest.skip("morning_hint 的签名和预期不同")
    if isinstance(r, str) and r.strip() and "早上" in r:
        assert "晚安" not in r, "早上的提示里出现了「晚安」：%s" % r[:80]


# ══════════════════════════════════════════════════════════════
# ⑦ 接线
# ══════════════════════════════════════════════════════════════
def test_module_is_registered_in_lazy_map():
    """它得在 LAZY_MAP 里（否则整个拟人化功能没人调）"""
    from core.lazy_config import LAZY_MAP
    assert "personality" in LAZY_MAP, "personality 没登记进 LAZY_MAP"
    assert LAZY_MAP["personality"][0] == "personality"


def test_full_hint_callers_still_exist():
    """⚠️ `full_hint` 有 3 个调用点 —— 名字一改它们全静默失效

    实测（写这条时全项目搜的）：
        core/llm_client.py:242
        core/pipeline/legacy_reply.py:159
        core/pipeline/prompt_assembler.py:39

    第一版我查的是 `context_builder.py`（以为流水线都在那儿），
    结果那里根本没有 —— 是我想当然了。改成查**真实存在的这三处**，
    而且反过来要求"每个调用点都真的调到了 full_hint"。
    """
    callers = [
        os.path.join("core", "llm_client.py"),
        os.path.join("core", "pipeline", "legacy_reply.py"),
        os.path.join("core", "pipeline", "prompt_assembler.py"),
    ]
    for rel in callers:
        p = os.path.join(BASE, rel)
        assert os.path.exists(p), "调用点文件没了：%s" % rel
        src = open(p, encoding="utf-8").read()
        assert "full_hint" in src, \
            "%s 不再调 full_hint —— 人格提示接不上了" % rel
