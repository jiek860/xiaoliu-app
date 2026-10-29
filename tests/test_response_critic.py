# -*- coding: utf-8 -*-
"""生成后校验器（批次 42.3）。"""
from core.chat.critic import ResponseCritic, render_plan_avoid
from core.pipeline.reply_pipeline import ReplyPipeline

ACK = {"act": "ack", "max_sentences": 1, "max_chars": 40, "question_back": False}
ANSWER = {"act": "answer", "max_sentences": 2, "max_chars": 60, "question_back": False}


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages):
        return self.reply


class FakeTrunk:
    def __init__(self, base=".", critic="shadow", rewrite=False, llm=None):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        if llm is not None:
            self.modules["llm"] = FakeLLM(llm)
        self._critic = critic
        self._rewrite = rewrite

    def rule(self, key, default=None):
        if key == "聊天.校验器":
            return self._critic
        if key == "聊天.校验重写":
            return self._rewrite
        return default

    def mem_recent(self, n=6):
        return []

    def _load_lazy(self, name):
        return self.modules.get(name)

    def _log(self, msg):
        return None


def test_clean_answer_passes():
    result = ResponseCritic().check("先给结论：改这里就行。", ANSWER, user_text="怎么改")
    assert result["ok"] is True
    assert result["issues"] == []


def test_too_many_sentences_truncated():
    result = ResponseCritic().check("第一句。第二句。第三句。", ACK, user_text="嗯")
    assert "too_long" in result["issues"]
    assert result["fixed_text"] == "第一句。"


def test_too_long_single_sentence_cut_at_boundary():
    text = "这" * 80
    result = ResponseCritic().check(text, ACK, user_text="嗯")
    assert len(result["fixed_text"]) <= 40
    assert result["fixed_text"].endswith("。")


def test_restate_removed():
    user = "为什么这个函数会报错"
    result = ResponseCritic().check(user + "，因为参数没传。", ANSWER, user_text=user)
    assert "restate" in result["issues"]
    assert result["fixed_text"].startswith("因为参数没传")


def test_duplicate_sentences_removed():
    result = ResponseCritic().check("先检查参数。先检查参数。", ANSWER, user_text="怎么查")
    assert "repeat" in result["issues"]
    assert result["fixed_text"].count("先检查参数") == 1


def test_banned_phrases_rewritten():
    result = ResponseCritic().check("作为AI，我无法直接改你的文件。", ANSWER, user_text="帮我改")
    assert "banned" in result["issues"]
    assert "作为AI" not in result["fixed_text"]
    assert "我无法" not in result["fixed_text"]


def test_bullets_flattened_for_short_ack():
    result = ResponseCritic().check("- 第一点\n- 第二点", ACK, user_text="嗯")
    assert "bullets" in result["issues"]
    assert "-" not in result["fixed_text"]
    assert "，" in result["fixed_text"]


def test_emoji_trimmed_to_budget():
    result = ResponseCritic().check("好耶😀😀😀", ACK, user_text="嗯")
    assert "emoji" in result["issues"]
    assert result["fixed_text"].count("😀") == 2


def test_extra_questions_removed():
    result = ResponseCritic().check("是这样？还是那样？", ANSWER, user_text="怎么弄")
    assert "question" in result["issues"]
    assert "？" not in result["fixed_text"]


def test_missing_question_added_when_plan_asks():
    plan = dict(ANSWER, question_back=True)
    result = ResponseCritic().check("还缺文件路径。", plan, user_text="帮我改")
    assert "question" in result["issues"]
    assert "？" in result["fixed_text"]


def test_off_topic_flagged_but_not_rewritten():
    result = ResponseCritic().check(
        "今天天气不错。", ANSWER, user_text="为什么函数参数没传进去")
    assert "off_topic" in result["issues"]
    assert result["fixed_text"] == "今天天气不错。"


def test_code_block_not_truncated():
    code = "```python\nprint('" + "x" * 100 + "')\n```"
    plan = dict(ANSWER, max_sentences=1, max_chars=20)
    result = ResponseCritic().check(code, plan, user_text="看看代码")
    assert result["fixed_text"] == code
    assert "too_long" in result["issues"]


def test_empty_answer():
    result = ResponseCritic().check("", ANSWER, user_text="你好")
    assert result["ok"] is False
    assert result["issues"] == ["empty"]


def test_bad_plan_numbers_do_not_raise():
    result = ResponseCritic().check("第一句。第二句。", {"max_chars": object(),
                                                        "max_sentences": None})
    assert isinstance(result["fixed_text"], str)
    assert result["fixed_text"]


def test_rewrite_used_when_enabled():
    critic = ResponseCritic(FakeTrunk(rewrite=True, llm="重写后的简短回复"))
    result = critic.check("作为AI，我无法帮你。", ANSWER, user_text="帮我改")
    assert result["source"] == "model"
    assert result["fixed_text"] == "重写后的简短回复"


def test_rewrite_skipped_when_disabled():
    critic = ResponseCritic(FakeTrunk(rewrite=False, llm="重写后的简短回复"))
    result = critic.check("作为AI，我无法帮你。", ANSWER, user_text="帮我改")
    assert result["source"] == "rule"
    assert result["fixed_text"] != "重写后的简短回复"


def test_rewrite_too_long_is_rejected():
    critic = ResponseCritic(FakeTrunk(rewrite=True, llm="长" * 200))
    result = critic.check("作为AI，我无法帮你。", ANSWER, user_text="帮我改")
    assert result["source"] == "rule"


def test_render_plan_avoid_dedupes():
    rows = render_plan_avoid({"avoid": ["说教", "说教", "列点"]})
    assert rows.count("说教") == 1
    assert "列点" in rows


def test_pipeline_critic_off_returns_unchanged(tmp_path):
    pipe = ReplyPipeline(FakeTrunk(tmp_path, critic="off"))
    answer, summary = pipe._critique("嗯", "第一句。第二句。", ACK)
    assert answer == "第一句。第二句。"
    assert summary == {}


def test_pipeline_critic_shadow_logs_but_keeps_text(tmp_path):
    pipe = ReplyPipeline(FakeTrunk(tmp_path, critic="shadow"))
    answer, summary = pipe._critique("嗯", "第一句。第二句。", ACK)
    assert answer == "第一句。第二句。"
    assert "too_long" in summary["issues"]
    assert summary["after"] < summary["before"]


def test_pipeline_critic_on_applies_fix(tmp_path):
    pipe = ReplyPipeline(FakeTrunk(tmp_path, critic="on"))
    answer, summary = pipe._critique("嗯", "第一句。第二句。", ACK)
    assert answer == "第一句。"
    assert summary["issues"]


def test_pipeline_critic_invalid_mode_defaults_to_shadow(tmp_path):
    pipe = ReplyPipeline(FakeTrunk(tmp_path, critic="loud"))
    assert pipe._critic_mode() == "shadow"
