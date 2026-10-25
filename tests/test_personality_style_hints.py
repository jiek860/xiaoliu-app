# -*- coding: utf-8 -*-
"""core/personality_style_hints.py 的同名测试：人格提示拼接与触发条件。

Host 里补上同模块外部的几个 hint 方法（真实实现分布在 personality 模块，
这里只需可控的占位值）。
"""
import time

import pytest

from core.personality_style_hints import PersonalityStyleHintsMixin


class FakeTrunk:
    def __init__(self, persona=""):
        self.config = {"ai_persona": persona}


class Host(PersonalityStyleHintsMixin):
    def __init__(self, base, trunk=None, **data):
        self.base = str(base)
        self.trunk = trunk or FakeTrunk()
        self.data = {
            "mood": "轻松", "energy": 60, "catchphrases": [], "plans": [],
            "narrative": [], "relation_stage": 3, "user_style": "简短",
            "birth_time": time.time(), "last_user_feeling": "",
            "last_active": time.time(), "guilt": [], "recent_user_msgs": [],
            "last_proactive_date": "",
        }
        self.data.update(data)
        self.saved = 0

    def _save(self):
        self.saved += 1

    # ── 外部 hint 的占位实现（真实实现在 personality 模块）──
    def update_emotion(self, text):
        return "【心情】平静"

    def relation_title_hint(self):
        return "【称呼】老朋友"

    def late_night_hint(self):
        return ""

    def weather_real_hint(self):
        return ""

    def roast_hint(self, text):
        return ""

    def comfort_hint(self, text):
        return ""


@pytest.fixture(autouse=True)
def _clear_caches():
    PersonalityStyleHintsMixin._bible_cache.clear()
    PersonalityStyleHintsMixin._hint_cache.clear()


def test_mood_hint_uses_mood_text(tmp_path):
    h = Host(tmp_path, mood="开心")
    assert "【你现在的心情：开心】" in h.mood_hint()
    assert "雀跃" in h.mood_hint()


def test_mood_hint_energy_adjusts_length(tmp_path):
    assert "回短点" in Host(tmp_path, mood="轻松", energy=10).mood_hint()
    assert "多说两句" in Host(tmp_path, mood="轻松", energy=95).mood_hint()


def test_catchphrase_hint(tmp_path):
    assert Host(tmp_path).catchphrase_hint() == ""
    h = Host(tmp_path, catchphrases=["好家伙", "整一个"])
    assert "好家伙" in h.catchphrase_hint()


def test_pending_plan_only_after_three_days(tmp_path):
    fresh = Host(tmp_path, plans=[{"text": "买书", "done": False,
                                   "time": time.time()}])
    assert fresh.pending_plan() is None
    old = Host(tmp_path, plans=[{"text": "买书", "done": False,
                                 "time": time.time() - 4 * 86400}])
    assert old.pending_plan() == "买书"
    done = Host(tmp_path, plans=[{"text": "买书", "done": True,
                                 "time": time.time() - 4 * 86400}])
    assert done.pending_plan() is None


def test_last_event_window(tmp_path):
    assert Host(tmp_path).last_event() is None
    recent = Host(tmp_path, narrative=[{"summary": "吃了火锅",
                                        "time": time.time() - 86400}])
    assert recent.last_event(3) == "吃了火锅"
    old = Host(tmp_path, narrative=[{"summary": "旧事",
                                     "time": time.time() - 10 * 86400}])
    assert old.last_event(3) is None


def test_get_tone_requires_close_relation(tmp_path):
    text = "拜拜"
    assert Host(tmp_path, relation_stage=1).get_tone(text) is None
    assert "那你走吧" in Host(tmp_path, relation_stage=2).get_tone(text)
    assert "去找它吧" in Host(tmp_path, relation_stage=3).get_tone("别的AI")
    assert "不好意思" in Host(tmp_path, relation_stage=3).get_tone("你真聪明")
    assert Host(tmp_path, relation_stage=3).get_tone("今天天气不错") is None


def test_short_reply_hint(tmp_path):
    h = Host(tmp_path)
    assert "别展开" in h.short_reply_hint("在吗")
    assert h.short_reply_hint("这是一个比较长的句子，需要完整展开") == ""


def test_short_reply_hint_accepts_none(tmp_path):
    # None 按空串处理：不崩溃，且给出"说得很短"的提示
    assert "别展开" in Host(tmp_path).short_reply_hint(None)


def test_repeat_hint_after_third_time(tmp_path):
    h = Host(tmp_path, recent_user_msgs=["帮我查一下天气怎么样"])
    assert h.repeat_hint("帮我查一下天气怎么样") == ""
    assert "之前聊过" in h.repeat_hint("帮我查一下天气怎么样")
    assert h.saved > 0


def test_feedback_hint_recent_praise(tmp_path):
    h = Host(tmp_path, guilt=[{"type": "praise", "text": "你真棒",
                               "time": time.time()}])
    assert "你上次还夸我呢" in h.feedback_hint()
    stale = Host(tmp_path, guilt=[{"type": "praise", "text": "你真棒",
                                   "time": time.time() - 5 * 86400}])
    assert stale.feedback_hint() == ""


def test_full_hint_handles_none(tmp_path):
    h = Host(tmp_path)
    out = h.full_hint(None)
    assert isinstance(out, str) and len(out) <= 500
    assert "心情" in out


def test_full_hint_includes_custom_persona(tmp_path):
    h = Host(tmp_path, trunk=FakeTrunk("嘴硬心软，重庆口音"))
    assert "【你的核心性格】嘴硬心软" in h.full_hint("你好")


def test_bible_hint_has_constitution_and_cache(tmp_path):
    h = Host(tmp_path)
    out = h.bible_hint("今天天气怎么样")
    assert "小6人格宪法" in out
    assert h._hint_cache["今天天气怎么样"] == out


def test_bible_hint_loads_category_file(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "emotion_bible.md").write_text("难过时要先陪着",
                                               encoding="utf-8")
    h = Host(tmp_path)
    out = h.bible_hint("我有点难过")
    assert "按需加载·分类圣经" in out and "难过时要先陪着" in out


def test_emoji_hint_mentions_mood(tmp_path):
    # emoji 是从心情对应集合里随机抽 2 个，不能断言某一个具体字符
    out = Host(tmp_path, mood="开心").emoji_hint()
    assert "表情包" in out
    assert set(out) & set("🎉😄✨🥳")


def test_make_poem_on_thirtieth_day(tmp_path):
    h = Host(tmp_path, birth_time=time.time() - 30 * 86400)
    poem = h.make_poem()
    assert poem and "三十天" in poem
    assert Host(tmp_path).make_poem() is None


def test_values_and_style_hints(tmp_path):
    assert "有自己的看法" in Host(tmp_path).values_hint()
    assert "别写长" in Host(tmp_path, user_style="简短").style_hint()
    assert Host(tmp_path, user_style="正常").style_hint() == ""


def test_curiosity_hint_gated_by_relation(tmp_path):
    assert Host(tmp_path, relation_stage=0).curiosity_hint() == ""
    assert "反问" in Host(tmp_path, relation_stage=1).curiosity_hint()


def test_sense_feeling_tags_emotion(tmp_path):
    h = Host(tmp_path)
    h.sense_feeling("累死了，真烦")
    assert h.data["last_user_feeling"] == "低落"
    h.sense_feeling("太好了哈哈哈哈")
    assert h.data["last_user_feeling"] == "开心"
    h.sense_feeling("谢谢你")
    assert h.data["last_user_feeling"] == "友好"


def test_few_shot_examples_shape():
    rows = PersonalityStyleHintsMixin.few_shot_examples()
    assert rows and all(set(r) == {"u", "a"} for r in rows)


def test_proactive_lines_once_per_day(tmp_path, monkeypatch):
    import core.personality_style_hints as psh

    class FakeDT:
        @staticmethod
        def now():
            class _N:
                hour = 9

                def strftime(self, fmt):
                    return "2026-10-25"
            return _N()

    monkeypatch.setattr(psh, "datetime", FakeDT)
    h = Host(tmp_path, last_active=time.time())
    first = h.proactive_lines()
    assert first
    assert h.proactive_lines() is None
