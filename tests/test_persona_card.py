# -*- coding: utf-8 -*-
"""分层人格卡（批次 42.4）。"""
import json
import os

from core.chat import persona_card
from core.chat.critic import ResponseCritic
from core.chat.persona_card import PersonaCard
from core.pipeline.prompt_assembler import PromptAssembler

ACK = {"act": "ack", "max_sentences": 1, "max_chars": 40, "question_back": False}


class FakeTrunk:
    def __init__(self, base=".", config=None, rules=None):
        self.base = str(base)
        self.config = config or {}
        self.rules = rules or {}
        self.modules = {}
        self._active_skill_prompt = ""

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def mem_recent(self, n=6):
        return []

    def _load_lazy(self, name):
        return None

    def _log(self, msg):
        return None


def test_real_card_loads():
    card = PersonaCard.load(".")
    assert card.version == "2026-10-29"
    assert card.style_names() == ["松弛", "毒舌", "温和", "专业", "口语化"]


def test_build_default_style_has_l1_and_l2():
    built = PersonaCard.load(".").build()
    assert "你是小6" in built["text"]
    assert "语气松弛" in built["text"]
    assert built["style"] == "松弛"
    assert built["layers"] == ["l1", "l2"]
    assert built["chars"] <= 520


def test_professional_style_disables_emoji():
    card = PersonaCard.load(".")
    built = card.build(style="专业")
    assert built["emoji_budget"] == 0
    assert "信息密度高" in built["text"]
    assert card.emoji_budget("专业") == 0


def test_unknown_style_falls_back_to_default():
    built = PersonaCard.load(".").build(style="不存在")
    assert built["style"] == "松弛"


def test_topic_layer_added():
    built = PersonaCard.load(".").build(state={"topic": "代码"})
    assert "先定位再给改法" in built["text"]
    assert "l3" in built["layers"]


def test_comfort_plan_promotes_emotion_layer():
    built = PersonaCard.load(".").build(
        state={"topic": "代码"}, plan={"act": "comfort"})
    assert "先定位再给改法" in built["text"]
    assert "先陪着" in built["text"]


def test_user_preferences_render_l4():
    built = PersonaCard.load(".").build(
        user_name="小王", prefs=["喜欢短句", "讨厌说教"])
    assert "关于小王" in built["text"]
    assert "喜欢短句" in built["text"]
    assert "l4" in built["layers"]


def test_card_respects_max_chars(tmp_path):
    data = dict(PersonaCard.load(".").data)
    data["max_chars"] = 40
    card = PersonaCard(base=str(tmp_path), data=data)
    built = card.build(style="松弛")
    assert built["chars"] <= 40


def test_missing_file_uses_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(persona_card, "_SEED_PATH", str(tmp_path / "nope.json"))
    card = PersonaCard.load(str(tmp_path))
    assert card.version == "builtin"
    assert card.style_names() == ["松弛", "口语化"]


def test_invalid_file_uses_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(persona_card, "_SEED_PATH", str(tmp_path / "nope.json"))
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "persona_tiers.json").write_text("{bad json", encoding="utf-8")
    card = PersonaCard.load(str(tmp_path))
    assert card.version == "builtin"


def test_user_file_overrides_seed(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "persona_tiers.json").write_text(json.dumps({
        "version": "user-1", "default_style": "温和",
    }, ensure_ascii=False), encoding="utf-8")
    card = PersonaCard.load(str(tmp_path))
    assert card.version == "user-1"
    assert card.data["default_style"] == "温和"


def test_banned_pairs_from_file():
    card = PersonaCard.load(".")
    words = card.banned_words()
    assert "作为AI" in words
    assert "希望对你有所帮助" in words
    assert ("作为AI", "我") in card.banned_pairs()


def test_assembler_shadow_records_but_keeps_old_persona():
    trunk = FakeTrunk(rules={"聊天.人格卡": "shadow"})
    pa = PromptAssembler(trunk)
    messages = pa.assemble("你好", "", True)
    assert "语气松弛" not in messages[0]["content"]
    assert pa.last_persona["mode"] == "shadow"
    assert pa.last_persona["style"] == "松弛"
    assert pa.last_persona["chars"] > 0


def test_assembler_on_uses_card_text():
    trunk = FakeTrunk(rules={"聊天.人格卡": "on"})
    pa = PromptAssembler(trunk)
    messages = pa.assemble("你好", "", True)
    assert "你是小6" in messages[0]["content"]
    assert "语气松弛" in messages[0]["content"]
    assert pa.last_persona["mode"] == "on"


def test_assembler_default_is_on():
    # 批次 D1：未显式配置时人格卡默认 on，真正替换系统提示词
    trunk = FakeTrunk()
    pa = PromptAssembler(trunk)
    messages = pa.assemble("你好", "", True)
    assert pa.last_persona["mode"] == "on"
    assert "语气松弛" in messages[0]["content"]


def test_length_hint_levels():
    # 批次 D4：简问短答、复杂问题可详细展开
    simple = PromptAssembler(FakeTrunk()).assemble("你好", "", True)
    assert any("回复长度：简短" in m["content"] for m in simple)
    detailed = PromptAssembler(FakeTrunk()).assemble(
        "能详细解释一下为什么吗", "", False)
    assert any("详细展开" in m["content"] for m in detailed)


def test_emotion_voice_injected_into_persona():
    # 批次 D5：负面情绪触发「先接住情绪」语气提示
    messages = PromptAssembler(FakeTrunk()).assemble("今天好累，不想动", "", False)
    assert "本轮语气" in messages[0]["content"]


def test_assembler_style_switch():
    trunk = FakeTrunk(rules={"聊天.人格卡": "on", "聊天.人格风格": "专业"})
    messages = PromptAssembler(trunk).assemble("你好", "", True)
    assert "信息密度高" in messages[0]["content"]


def test_assembler_off_skips_card():
    trunk = FakeTrunk(rules={"聊天.人格卡": "off"})
    pa = PromptAssembler(trunk)
    messages = pa.assemble("你好", "", True)
    assert pa.last_persona["mode"] == "off"
    assert pa.last_persona["gray"] is False
    assert "你是小6，住在用户电脑里的AI朋友。" == messages[0]["content"]


def test_custom_persona_wins_over_card_on():
    trunk = FakeTrunk(config={"ai_persona": "你是自定义助手。"},
                      rules={"聊天.人格卡": "on"})
    messages = PromptAssembler(trunk).assemble("你好", "", True)
    assert messages[0]["content"].startswith("你是自定义助手。")


def test_critic_uses_card_banned_words(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "persona_tiers.json").write_text(json.dumps({
        "version": "test",
        "banned": {"瞎编": "", "张口就来": ""},
    }, ensure_ascii=False), encoding="utf-8")
    result = ResponseCritic(FakeTrunk(base=tmp_path)).check(
        "你别瞎编。", ACK, user_text="嗯")
    assert "banned" in result["issues"]
    assert "瞎编" not in result["fixed_text"]


def test_emoji_budget_flows_into_critic():
    card = PersonaCard.load(".")
    plan = dict(ACK, emoji_budget=card.emoji_budget("专业"))
    result = ResponseCritic().check("好耶😀", plan, user_text="嗯")
    assert "emoji" in result["issues"]
    assert "😀" not in result["fixed_text"]
