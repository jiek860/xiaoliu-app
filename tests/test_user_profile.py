# -*- coding: utf-8 -*-
"""用户画像（批次 O2）：称呼/语气偏好 → 人格卡 L4，以及记忆冲突确认。"""
import json
import os

from core.chat import user_profile
from core.chat.persona_card import PersonaCard
from core.chat.user_profile import collect, name_from_text
from core.pipeline.prompt_assembler import PromptAssembler
from core.vector_store import VectorStore
from modules.installed.memory_loop import MemoryPipeline


class FakeTrunk:
    def __init__(self, base=".", config=None, rules=None, modules=None):
        self.base = str(base)
        self.config = config or {}
        self.rules = rules or {}
        self.modules = modules or {}
        self._active_skill_prompt = ""

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def mem_recent(self, n=6):
        return []

    def _load_lazy(self, name):
        return None

    def _log(self, msg):
        return None


def _write(base, name, rows):
    folder = os.path.join(str(base), "data")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fp:
        fp.write(rows if isinstance(rows, str) else json.dumps(rows, ensure_ascii=False))


def test_name_from_text_only_takes_self_intro():
    assert name_from_text("以后叫我老王吧") == "老王"
    assert name_from_text("我叫小王，在杭州上班") == "小王"
    assert name_from_text("你可以叫我 Alex") == "Alex"
    assert name_from_text("我叫了个外卖") == ""
    assert name_from_text("今天天气不错") == ""


def test_collect_reads_name_style_and_prefs(tmp_path):
    _write(tmp_path, "personality.json",
           {"user_name": "小王", "user_style": "简短"})
    _write(tmp_path, "memory_cards.jsonl", "\n".join([
        json.dumps({"facts": ["偏好:喜欢短句"], "time": 1}, ensure_ascii=False),
        json.dumps({"facts": ["偏好:讨厌说教"], "time": 2}, ensure_ascii=False),
    ]) + "\n")
    profile = collect(base=str(tmp_path))
    assert profile["name"] == "小王"
    assert "喜欢短句" in profile["prefs"]
    assert "讨厌说教" in profile["prefs"]
    assert "说话喜欢简短" in profile["prefs"]
    assert profile["style"] == "简短"


def test_collect_prefers_newest_prefs_and_survives_bad_lines(tmp_path):
    _write(tmp_path, "memory_cards.jsonl", "\n".join([
        json.dumps({"facts": ["偏好:喜欢旧写法"], "time": 1},
                   ensure_ascii=False),
        "坏行",
        json.dumps({"facts": ["偏好:喜欢新写法"], "time": 2},
                   ensure_ascii=False),
    ]) + "\n")
    profile = collect(base=str(tmp_path), limit=2)
    assert profile["name"] == ""
    assert profile["prefs"][0] == "喜欢新写法"


def test_collect_reads_name_from_memory_card(tmp_path):
    _write(tmp_path, "memory_cards.jsonl",
           json.dumps({"facts": ["事实:以后叫我老王"],
                       "time": 3}, ensure_ascii=False) + "\n")
    assert collect(base=str(tmp_path))["name"] == "老王"


def test_prompt_assembler_writes_profile_into_l4(tmp_path):
    _write(tmp_path, "personality.json",
           {"user_name": "小王", "user_style": "简短"})
    _write(tmp_path, "memory_cards.jsonl",
           json.dumps({"facts": ["偏好:喜欢短句", "偏好:讨厌说教"],
                       "time": 1}, ensure_ascii=False) + "\n")
    trunk = FakeTrunk(base=tmp_path)
    pa = PromptAssembler(trunk)
    messages = pa.assemble("你好", "", True)
    assert "关于小王" in messages[0]["content"]
    assert "喜欢短句" in messages[0]["content"]
    assert pa.last_persona["profile"]["name"] is True


def test_persona_card_name_only_does_not_render_half_sentence():
    built = PersonaCard.load(".").build(user_name="小王")
    assert "关于小王：。" not in built["text"]
    assert "小王" in built["text"]
    assert "l4" in built["layers"]


def test_vector_store_prefs_reads_without_embedding():
    store = VectorStore.__new__(VectorStore)
    store.data = [
        {"text": "偏好:喜欢短句"},
        {"text": "我喜欢蓝色"},
        {"text": "今天下雨"},
        {"text": "偏好:喜欢短句"},
    ]
    assert store.prefs(2) == ["喜欢短句", "喜欢蓝色"]


def test_memory_loop_user_prefs_merges_vector_hits(tmp_path):
    class _VS:
        def prefs(self, limit=3):
            return ["喜欢蓝色"]

    _write(tmp_path, "memory_cards.jsonl",
           json.dumps({"facts": ["偏好:喜欢短句"],
                       "time": 1}, ensure_ascii=False) + "\n")
    trunk = FakeTrunk(base=tmp_path, modules={"vector_store": _VS()})
    pipe = MemoryPipeline(trunk)
    row = pipe.user_prefs()
    assert "喜欢短句" in row["prefs"]
    assert "喜欢蓝色" in row["prefs"]


def test_personality_learn_user_name_persists(tmp_path):
    from core.personality_state import PersonalityStateMixin

    class _Pers(PersonalityStateMixin):
        def __init__(self, path):
            self.path = path
            self.data = self._load()

    path = os.path.join(str(tmp_path), "data", "personality.json")
    os.makedirs(os.path.join(str(tmp_path), "data"), exist_ok=True)
    pers = _Pers(path)
    assert pers.learn_user_name("以后叫我老王吧") == "老王"
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["user_name"] == "老王"
    assert collect(base=str(tmp_path))["name"] == "老王"
