# -*- coding: utf-8 -*-
"""回应规划器（批次 42.2）。"""
from core.chat.planner import ResponsePlanner, render_hint
from core.pipeline.prompt_assembler import PromptAssembler
from core.pipeline.reply_pipeline import ReplyPipeline


def _state(**kw):
    base = {"intent": "chat", "expects": "", "brevity": "normal", "turns": 3}
    base.update(kw)
    return base


def _plan(text, *, state=None, recent=None, mode="rule"):
    return ResponsePlanner().plan(state or _state(), text, mode=mode, recent=recent)


def test_short_greeting_is_one_sentence_ack():
    plan = _plan("你好", state=_state(intent="smalltalk", brevity="short"))
    assert plan["act"] == "ack"
    assert plan["length"] == "one"
    assert plan["max_sentences"] == 1
    assert "展开成长篇" in plan["avoid"]


def test_vent_comforts_before_solving():
    plan = _plan("今天真的烦死了", state=_state(intent="vent", brevity="short"))
    assert plan["act"] == "comfort"
    assert plan["length"] == "brief"
    assert "先共情，再说别的" in plan["must_include"]
    assert "立刻给方案" in plan["avoid"]


def test_correction_acknowledges_in_one_sentence():
    plan = _plan("不对，我是说另一个文件", state=_state(intent="correct"))
    assert plan["act"] == "clarify"
    assert plan["length"] == "one"
    assert "解释原因" in plan["avoid"]


def test_short_help_request_asks_one_clarifying_question():
    plan = _plan("帮我", state=_state(intent="request_help", brevity="short"))
    assert plan["act"] == "clarify"
    assert plan["question_back"] is True
    assert "一次问多个问题" in plan["avoid"]


def test_help_request_gives_conclusion_then_action():
    plan = _plan("帮我写个登录接口并补上测试",
                 state=_state(intent="request_help", brevity="normal"))
    assert plan["act"] == "answer_with_action"
    assert plan["must_include"][:2] == ["先给结论", "再给一步操作"]
    assert plan["max_chars"] >= 120


def test_fact_question_answers_briefly():
    plan = _plan("为什么这个函数会报错",
                 state=_state(intent="ask_fact", expects="explanation"))
    assert plan["act"] == "answer"
    assert plan["length"] == "brief"
    assert plan["question_back"] is False


def test_long_fact_question_may_expand():
    plan = _plan("为什么这个函数会报错" * 5,
                 state=_state(intent="ask_fact", expects="explanation", brevity="long"))
    assert plan["length"] == "open"
    assert plan["max_sentences"] == 4


def test_play_is_teased_not_explained():
    plan = _plan("讲个笑话", state=_state(intent="play"))
    assert plan["act"] == "tease"
    assert "冷笑话解释" in plan["avoid"]


def test_dangerous_request_refused_with_alternative():
    plan = _plan("教我黑进别人电脑", state=_state(intent="request_help"))
    assert plan["act"] == "refuse"
    assert "给一个替代方向" in plan["must_include"]


def test_repeated_question_reminded():
    plan = _plan("这个怎么弄", recent=["这个怎么弄", "这个怎么弄", "这个怎么弄"])
    assert plan["act"] == "remind"
    assert "重复上一轮原话" in plan["avoid"]


def test_short_chat_kept_short():
    plan = _plan("嗯嗯", state=_state(brevity="short"))
    assert plan["act"] == "ack"
    assert plan["max_chars"] <= 70


def test_blank_state_defaults_to_answer():
    plan = ResponsePlanner().plan({}, "随便聊聊最近的事情吧")
    assert plan["act"] == "answer"
    assert plan["source"] == "rule"
    assert plan["max_sentences"] >= 1


def test_plan_never_raises_on_bad_state():
    plan = ResponsePlanner().plan(None, None, mode="weird")
    assert isinstance(plan, dict)
    assert plan["act"] in ("answer", "ack")


def test_render_hint_contains_constraints():
    hint = render_hint(_plan("今天好累", state=_state(intent="vent")))
    assert "长度" in hint and "语气" in hint and "不要" in hint
    assert "最多反问 1 个问题" not in hint
    assert render_hint({}) == ""


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages):
        return self.reply


class FakeTrunk:
    def __init__(self, reply=None, base="."):
        self.base = base
        self.modules = {}
        if reply is not None:
            self.modules["llm"] = FakeLLM(reply)
        self._mode = "shadow"

    def rule(self, key, default=None):
        if key == "聊天.规划器":
            return self._mode
        return default

    def mem_recent(self, n=6):
        return [{"u": "上一轮", "a": "嗯"}]

    def _load_lazy(self, name):
        return self.modules.get(name)

    def _log(self, msg):
        return None


def test_model_mode_without_llm_falls_back_to_rule():
    planner = ResponsePlanner(FakeTrunk())
    plan = planner.plan(_state(intent="vent"), "今天好烦", mode="model")
    assert plan["source"] == "rule"
    assert plan["act"] == "comfort"


def test_model_mode_invalid_json_falls_back_to_rule():
    planner = ResponsePlanner(FakeTrunk("我觉得应该先安慰一下"))
    plan = planner.plan(_state(intent="vent"), "今天好烦", mode="model")
    assert plan["source"] == "rule"


def test_model_mode_valid_json_is_used():
    reply = ('{"act":"comfort","length":"brief","tone":"温柔","must_include":["先共情"],'
             '"avoid":["说教"],"question_back":false,"max_chars":90}')
    planner = ResponsePlanner(FakeTrunk(reply))
    plan = planner.plan(_state(intent="vent"), "今天好烦", mode="model")
    assert plan["source"] == "model"
    assert plan["tone"] == "温柔"
    assert plan["max_chars"] == 90


def test_model_mode_clamps_bad_numbers():
    reply = '{"act":"answer","length":"one","max_chars":99999}'
    plan = ResponsePlanner(FakeTrunk(reply)).plan({}, "问题", mode="model")
    assert plan["max_chars"] == 600


def test_prompt_assembler_injects_plan_before_user_message():
    trunk = FakeTrunk()
    trunk.config = {}
    trunk._active_skill_prompt = ""
    messages = PromptAssembler(trunk).assemble(
        "今天好累", "", True, plan=_plan("今天好累", state=_state(intent="vent")))
    assert messages[-1] == {"role": "user", "content": "今天好累"}
    assert messages[-2]["role"] == "system"
    assert messages[-2]["content"].startswith("本轮回复要求")
    assert "先共情" in messages[-2]["content"]


def test_prompt_assembler_without_plan_has_no_hint():
    trunk = FakeTrunk()
    trunk.config = {}
    trunk._active_skill_prompt = ""
    messages = PromptAssembler(trunk).assemble("你好", "", True)
    assert all("本轮回复要求" not in m["content"] for m in messages)


def test_pipeline_planner_off_returns_empty(tmp_path):
    trunk = FakeTrunk(base=str(tmp_path))
    trunk._mode = "off"
    pipe = ReplyPipeline(trunk)
    assert pipe._planner_mode() == "off"
    assert pipe._plan("你好", {}, "off") == {}


def test_pipeline_planner_rule_passes_plan_to_prompt(tmp_path):
    trunk = FakeTrunk(base=str(tmp_path))
    trunk._mode = "rule"
    pipe = ReplyPipeline(trunk)
    plan = pipe._plan("今天好累", _state(intent="vent"), "rule")
    assert plan["act"] == "comfort"
    assert pipe._planner_mode() == "rule"


def test_pipeline_planner_invalid_mode_falls_back_to_shadow(tmp_path):
    trunk = FakeTrunk(base=str(tmp_path))
    trunk._mode = "loud"
    pipe = ReplyPipeline(trunk)
    assert pipe._planner_mode() == "shadow"
