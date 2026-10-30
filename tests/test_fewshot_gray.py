# -*- coding: utf-8 -*-
"""少样本示例 + 灰度分流（批次 42.5）。"""
import json

from core.chat import fewshot as fewshot_mod
from core.chat.fewshot import pick
from core.pipeline.prompt_assembler import PromptAssembler
from core.pipeline.reply_pipeline import ReplyPipeline

ACK = {"act": "ack", "max_sentences": 1, "max_chars": 40, "question_back": False}


class FakeTrunk:
    def __init__(self, base=".", rules=None):
        self.base = str(base)
        self.config = {}
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


def test_real_file_has_twelve_examples():
    with open(fewshot_mod._SEED_PATH, encoding="utf-8") as fp:
        assert len(json.load(fp)) == 12


def test_user_file_overrides_seed(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "chat_fewshot.json").write_text(json.dumps([
        {"id": "u1", "topic": "代码", "act": "ack", "u": "自定义", "a": "好。"},
    ], ensure_ascii=False), encoding="utf-8")
    rows = pick(str(tmp_path), topic="代码", act="ack", limit=2)
    assert [r["u"] for r in rows] == ["自定义"]


def test_pick_prefers_act_then_topic():
    rows = pick(".", topic="代码", act="answer_with_action", limit=2)
    assert rows[0]["u"] == "帮我把这个函数改成支持空列表"
    assert len(rows) <= 2


def test_pick_topic_only():
    rows = pick(".", topic="情绪", limit=2)
    assert all("累" in r["u"] or "焦虑" in r["u"] for r in rows)


def test_pick_no_match_returns_empty():
    assert pick(".", topic="不存在的主题", act="不存在的动作") == []


def test_pick_missing_file_uses_builtin(tmp_path, monkeypatch):
    monkeypatch.setattr(fewshot_mod, "_SEED_PATH", str(tmp_path / "nope.json"))
    rows = pick(str(tmp_path), limit=2)
    assert len(rows) == 2
    assert rows[0]["u"] == "在吗"


def test_assembler_injects_examples_when_plan_given():
    trunk = FakeTrunk()
    messages = PromptAssembler(trunk).assemble(
        "帮我看看", "", True, plan={"act": "answer_with_action"},
        state={"topic": "代码"})
    user_rows = [m["content"] for m in messages if m["role"] == "user"]
    assert "帮我把这个函数改成支持空列表" in user_rows
    assert any("空判断" in m["content"] for m in messages
               if m["role"] == "assistant")


def test_assembler_shadow_without_plan_keeps_examples_empty():
    # 批次 D4：新增 1 条长度提示 system 段，但仍不含任何 few-shot 示例
    messages = PromptAssembler(FakeTrunk()).assemble("你好", "", True)
    assert [m for m in messages if m["role"] == "assistant"] == []


def test_assembler_card_on_uses_state_topic():
    trunk = FakeTrunk(rules={"聊天.人格卡": "on"})
    messages = PromptAssembler(trunk).assemble(
        "能帮我看看吗", "", True, state={"topic": "代码"})
    user_rows = [m["content"] for m in messages if m["role"] == "user"]
    assert "能帮我看看吗" in user_rows
    assert "能帮我看看吗" in user_rows and len(user_rows) >= 2


def test_assembler_gray_injects_even_in_shadow():
    messages = PromptAssembler(FakeTrunk()).assemble(
        "今天累死了", "", True, state={"topic": "情绪"}, gray=True)
    user_rows = [m["content"] for m in messages if m["role"] == "user"]
    assert "今天累死了" in user_rows
    assert len(user_rows) >= 2


def test_gray_off_by_default():
    pipe = ReplyPipeline(FakeTrunk())
    assert pipe._gray_on({"session": "s_1"}) is False


def test_gray_hundred_is_on():
    pipe = ReplyPipeline(FakeTrunk(rules={"聊天.灰度比例": 100}))
    assert pipe._gray_on({}) is True


def test_gray_without_session_is_off():
    pipe = ReplyPipeline(FakeTrunk(rules={"聊天.灰度比例": 50}))
    assert pipe._gray_on({}) is False


def test_gray_is_stable_for_same_session():
    pipe = ReplyPipeline(FakeTrunk(rules={"聊天.灰度比例": 50}))
    session = {"session": "s_20261029_1234"}
    assert pipe._gray_on(session) == pipe._gray_on(session)


def test_gray_forces_critic_on(tmp_path):
    pipe = ReplyPipeline(FakeTrunk(tmp_path, rules={"聊天.校验器": "shadow"}))
    answer, summary = pipe._critique("嗯", "第一句。第二句。", ACK, gray=True)
    assert answer == "第一句。"
    assert summary["issues"]


def test_gray_persona_mode_on():
    trunk = FakeTrunk(rules={"聊天.人格卡": "shadow"})
    pa = PromptAssembler(trunk)
    pa.assemble("你好", "", True, gray=True)
    assert pa.last_persona["mode"] == "on"
    assert pa.last_persona["gray"] is True
