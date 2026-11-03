# -*- coding: utf-8 -*-
"""去 AI 腔后处理（core/chat/deai.py）。

为什么单独测：这一层的意义就是"校验器 shadow 时也生效"，
所以除了纯函数用例，必须有一条走 ReplyPipeline._critique 的集成用例。
"""
from core.chat.deai import deai, strip_ai_tone
from core.pipeline import legacy_reply
from core.pipeline.reply_pipeline import ReplyPipeline

ACK = {"act": "ack", "max_sentences": 1, "max_chars": 40, "question_back": False}


class FakeTrunk:
    def __init__(self, base=".", critic="shadow"):
        self.base = str(base)
        self.config = {}
        self.modules = {}
        self._critic = critic

    def rule(self, key, default=None):
        if key == "聊天.校验器":
            return self._critic
        return default

    def mem_recent(self, n=6):
        return []

    def _load_lazy(self, name):
        return self.modules.get(name)

    def _log(self, msg):
        return None


# ---------------- 纯函数 ----------------
def test_removes_self_intro_at_head():
    out = deai("作为一个AI，我不能帮你删库。")["text"]
    assert "作为" not in out
    assert out.startswith("我不能帮你删库")


def test_removes_self_intro_in_middle():
    out = deai("我作为一个AI，只能给你建议。")["text"]
    assert "作为" not in out
    assert "我我" not in out


def test_removes_customer_service_lines():
    out = deai("这个我帮你弄，很高兴为您服务，如果还有问题，随时告诉我。")["text"]
    assert "很高兴为您服务" not in out
    assert "随时告诉我" not in out
    assert out == "这个我帮你弄。"


def test_removes_template_prefixes():
    out = deai("首先，打开设置；其次，点检查更新。总之，先备份。")["text"]
    assert "首先" not in out
    assert "其次" not in out
    assert "总之" not in out
    assert "打开设置" in out


def test_removes_filler_without_deleting_detail():
    out = deai("需要注意的是，这个接口有频率限制，一天最多 100 次。")["text"]
    assert "需要注意的是" not in out
    assert "100 次" in out


def test_code_block_is_untouched():
    raw = ("这样写：\n```python\n# 首先，作为AI 我先打印\n"
           "print(1)\n```\n先跑一下看看。")
    out = deai(raw)["text"]
    assert "# 首先，作为AI 我先打印" in out
    assert "```python" in out


def test_pure_filler_keeps_original():
    # 整条回复都是客套话：宁可留原样，也不能清成空白
    raw = "希望对你有所帮助。"
    result = deai(raw)
    assert result["text"] == raw
    assert result["hits"] == []


def test_plain_reply_is_unchanged():
    raw = "这个我熟，先看下你是不是把 venv 装到 C 盘了。"
    result = deai(raw)
    assert result["text"] == raw
    assert result["hits"] == []


def test_hits_reported():
    assert "自称AI" in deai("作为一个AI，我不太能。")["hits"]
    assert "模板前缀" in deai("其次，你得先装依赖。")["hits"]


def test_blank_and_none_are_safe():
    assert deai("")["text"] == ""
    assert deai(None)["text"] == ""
    assert deai("   \n ")["hits"] == []


def test_idempotent():
    raw = "作为一个AI，我不能删库。希望对你有所帮助。"
    once = strip_ai_tone(raw)
    assert strip_ai_tone(once) == once


# ---------------- 没有数据时的"硬凑一句"（2026-11-01 用户截图）----------------
def test_removes_self_denial_robot_sentence():
    """「我并没有情感…我是一个AI机器人，我的任务是为用户提供服务」整段删掉"""
    raw = ("【小6】\n抱歉，我刚刚的回复有误，我并没有情感，所以不能感受到高兴，"
           "我是一个AI机器人，我的任务是为用户提供服务。如果您有其他的问题，"
           "您可以随时问我。")
    result = deai(raw)
    out = result["text"]
    assert "情感" not in out
    assert "AI机器人" not in out
    assert "为用户提供服务" not in out
    assert "自我否定" in result["hits"]
    assert "抱歉" in out          # 道歉是真的，留着


def test_removes_empty_promise():
    """「请稍等片刻，我会尽快为您查询并回复」—— 它其实永远不会查"""
    raw = ("好的，请稍等片刻，我会尽快为您查询并回复。"
           "如果您有其他要求，也欢迎随时告诉我。")
    result = deai(raw)
    out = result["text"]
    assert "请稍等" not in out
    assert "尽快" not in out
    assert "随时告诉我" not in out
    assert "空许诺" in result["hits"]


def test_real_empathy_is_kept():
    """「我不能感受到你的痛苦」是共情，不是自我否定，不能删"""
    raw = "我不能感受到你的痛苦，但我在。"
    assert deai(raw)["hits"] == []
    assert deai(raw)["text"] == raw


def test_real_result_is_kept():
    """有结果的句子（「我查到了…」）不能当成空许诺删掉"""
    raw = "我查到了，最近的一家烧烤店在解放碑，走路 10 分钟。"
    assert deai(raw)["text"] == raw
    assert deai(raw)["hits"] == []


# ---------------- 接入回复管线 ----------------
def test_pipeline_deai_runs_with_critic_off():
    pipe = ReplyPipeline(FakeTrunk(critic="off"))
    answer, summary = pipe._critique(
        "嗯", "作为一个AI，我帮你把缓存清了。希望对你有所帮助。", ACK)
    assert "作为" not in answer
    assert "希望对你有所帮助" not in answer
    assert "自称AI" in summary["issues"]


def test_pipeline_deai_runs_with_critic_shadow():
    pipe = ReplyPipeline(FakeTrunk(critic="shadow"))
    answer, summary = pipe._critique(
        "嗯", "首先，打开设置。其次，点检查更新。", ACK)
    assert answer.startswith("打开设置")
    assert "模板前缀" in summary["issues"]


def test_pipeline_deai_is_noop_for_clean_text():
    pipe = ReplyPipeline(FakeTrunk(critic="off"))
    answer, summary = pipe._critique("嗯", "这个我帮你弄。", ACK)
    assert answer == "这个我帮你弄。"
    assert summary == {}


def test_legacy_reply_has_same_deai():
    assert "作为" not in legacy_reply._deai("作为一个AI，我不太能。")
    assert legacy_reply._deai("这个我帮你弄。") == "这个我帮你弄。"


# ---------------- 降级到非流式时别丢掉拼好的提示词 ----------------
# 本地 `LLMClient._try_local` 在 inject_persona=True 时会把调用方所有 system
# 消息换成一句通用人格 —— 人格卡 / 上下文 / 说话要求（TONE_HINT）全丢。
class _RecordingLLM:
    def __init__(self):
        self.kwargs = None

    def stream_chat(self, messages, on_token=None, cancel_token=None):
        return ""            # 模拟流式失败

    def chat(self, messages, **kwargs):
        self.kwargs = kwargs
        return "好"


class _LegacyLLM:
    """老接口：只收 messages，不认 inject_persona。"""
    def chat(self, messages):
        return "好"


def test_dispatcher_fallback_keeps_composed_prompt():
    from core.pipeline.llm_dispatcher import LLMDispatcher
    trunk = FakeTrunk()
    llm = _RecordingLLM()
    trunk.modules = {"llm": llm}
    answer = LLMDispatcher(trunk).dispatch(
        [{"role": "system", "content": "拼好的提示词"}], on_token=lambda t: None)
    assert answer == "好"
    assert llm.kwargs == {"inject_persona": False}


def test_legacy_fallback_keeps_composed_prompt():
    out = legacy_reply._chat_composed(_RecordingLLM(), [{"role": "user", "content": "嗯"}])
    assert out == "好"


def test_legacy_fallback_tolerates_old_llm_signature():
    assert legacy_reply._chat_composed(_LegacyLLM(), []) == "好"
    from core.pipeline.llm_dispatcher import LLMDispatcher
    assert LLMDispatcher._fallback_chat(_LegacyLLM(), []) == "好"
