# -*- coding: utf-8 -*-
"""聊天稳健性（第 3 批）：失败双判 + 失败分类 + 流式卡顿看门狗。"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import failure_classify as fc  # noqa: E402
from core.stream_guard import StreamStallGuard, guard_seconds  # noqa: E402
from core.trunk_reply import TrunkReplyMixin  # noqa: E402


class _Trunk(TrunkReplyMixin):
    def __init__(self, config=None):
        self.config = dict(config or {})
        self.modules = {}
        self.logs = []

    def _log(self, msg, level="INFO"):
        self.logs.append(msg)

    def call(self, mod, method, *a, **k):
        return {"ok": True}


class _Resp:
    """假流响应：记录是否被 close。"""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- 失败双判

def test_empty_and_error_placeholder_are_failures():
    assert fc.looks_failed("") is True
    assert fc.looks_failed(None) is True
    assert fc.looks_failed("   ") is True
    # 短错误（原来 <60 字会被当成正常回复直接显示）
    assert fc.looks_failed("本地模型错误: 连接失败") is True
    assert fc.looks_failed("⚠ 连不上本地 Ollama（11434 端口）") is True
    assert fc.classify("本地模型错误: read timed out") == "timeout"


def test_normal_answers_are_not_failures():
    assert fc.looks_failed("好呀，今天去哪儿玩？") is False
    long_ok = ("你可以去「设置 → 模型」里填 API Key，填完点保存就行。"
               "如果还是 401，说明这个 Key 没有该模型的权限。")
    assert fc.classify(long_ok) == "", "聊 API Key 的正常回答不能被判成鉴权失败"
    assert fc.looks_failed(long_ok) is False


def test_failure_kinds_are_classified():
    assert fc.classify(error="requests.exceptions.ReadTimeout: read timed out") == "timeout"
    assert fc.classify(error="401 Unauthorized") == "auth"
    assert fc.classify(error="429 rate limit exceeded") == "rate_limit"
    assert fc.classify(error="maximum context length exceeded") == "context_overflow"
    assert fc.classify(error="connection refused") == "network"
    assert fc.classify("") == "empty"
    assert fc.classify(error="完全看不懂的错误码") == "unknown"
    # 用户可见的正常文字不参与分类（只有错误文本才按异常分类）
    assert fc.classify("完全看不懂的错误码") == ""


def test_refusal_keeps_model_wording():
    refusal = "抱歉，我无法帮助修改这个用于绕过登录的脚本。"
    assert fc.classify(refusal) == "refusal"
    assert fc.keep_answer("refusal") is True, "拒答不能被兜底话吞掉"


def test_plans_drive_retry_and_shrink_and_hints():
    assert fc.should_retry("timeout") is True
    assert fc.should_shrink_context("context_overflow") is True
    assert fc.should_retry("auth") is False, "鉴权失败重试只会一直 401"
    assert fc.hint("auth") and "API Key" in fc.hint("auth")
    assert fc.hint("refusal") == ""


# ---------------------------------------------------------------- trunk 接线

def test_trunk_looks_failed_delegates_to_classifier():
    t = _Trunk()
    assert t._looks_failed("") is True
    assert t._looks_failed("今天天气不错") is False
    assert t._failure_kind("本地模型错误: timeout") == "timeout"
    assert t._failure_kind("正常回答") == ""


def test_shrunk_context_restores_budget_even_on_failure():
    t = _Trunk({"context_token_budget": 6000})
    t._reply_with_shrunk_context("随便问问")
    assert t.config["context_token_budget"] == 6000, "临时收窄必须还原"
    assert any("收窄" in line for line in t.logs)


# ---------------------------------------------------------------- 流式卡顿

def test_stall_guard_closes_stream_when_tokens_stop():
    clock = _Clock()
    resp = _Resp()
    guard = StreamStallGuard(5, clock=clock).bind(resp)
    guard.touch()
    assert guard.check_once() is False
    clock.now += 10          # 10 秒没有任何 token
    assert guard.check_once() is True
    assert guard.stalled is True
    assert resp.closed is True


def test_stall_guard_touch_keeps_it_alive():
    clock = _Clock()
    resp = _Resp()
    guard = StreamStallGuard(5, clock=clock).bind(resp)
    for _ in range(3):
        clock.now += 4
        guard.touch()
    assert guard.check_once() is False
    assert resp.closed is False


def test_stall_guard_seconds_from_config():
    assert guard_seconds({}) >= 5
    assert guard_seconds({"流式卡顿超时": 30}) == 30
    # 脏数据不能把阈值变成 0（那会把每一次正常停顿都当卡顿）
    assert guard_seconds({"流式卡顿超时": "abc"}) >= 5
    assert guard_seconds({"stream_stall_timeout": 999}) <= 120
