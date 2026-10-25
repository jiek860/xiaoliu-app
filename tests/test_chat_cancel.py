# -*- coding: utf-8 -*-
"""批次 1：真取消链路（Esc 停止必须真的停后台，而不是只停界面）"""
import json
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.cancel_token import CancelToken  # noqa: E402


# ---------------------------------------------------------------- CancelToken

def test_cancel_token_sets_flag_and_closes_bound_resource():
    token = CancelToken()
    closed = []
    token.bind(lambda: closed.append("stream"))
    assert token.is_cancelled() is False
    token.cancel()
    assert token.is_cancelled() is True
    assert closed == ["stream"]


def test_cancel_token_bind_after_cancel_closes_immediately():
    token = CancelToken()
    token.cancel()
    closed = []
    token.bind(lambda: closed.append("late"))
    assert closed == ["late"]


def test_cancel_token_unbind_skips_closer():
    token = CancelToken()
    closed = []
    closer = lambda: closed.append("x")  # noqa: E731
    token.bind(closer)
    token.unbind(closer)
    token.cancel()
    assert closed == []


# ---------------------------------------------------------------- StreamWorker

class _WaitingTrunk:
    """模拟卡在生成中的模型：只有收到取消才会退出"""

    def __init__(self):
        self.started = threading.Event()
        self.finished = threading.Event()
        self.tokens = []

    def _log(self, *_a, **_k):
        return None

    def reply(self, msg, on_token=None, force_chat=False, cancel_token=None):
        self.started.set()
        for i in range(500):
            if cancel_token is not None and cancel_token.is_cancelled():
                self.finished.set()
                return "已收到的内容"
            if on_token:
                on_token("t%d" % i)
                self.tokens.append("t%d" % i)
            time.sleep(0.01)
        return ""


def test_stream_worker_stop_really_cancels_running_reply(monkeypatch):
    import gui.workers as workers
    monkeypatch.setattr(workers, "_reg_start", lambda *_a, **_k: "")
    monkeypatch.setattr(workers, "_reg_finish", lambda *_a, **_k: None)

    trunk = _WaitingTrunk()
    w = workers.StreamWorker(trunk, "讲个长故事")
    w.start()
    assert trunk.started.wait(2), "worker 没有进入 reply"
    w.stop()
    assert trunk.finished.wait(2), "stop() 之后 reply 仍在跑（取消没有生效）"
    assert w.wait(3000), "取消后线程没有退出"
    assert w.is_cancelled() is True
    # 取消后不再向界面推 token
    count = len(trunk.tokens)
    w._guarded_token("迟到")
    time.sleep(0.05)
    assert len(trunk.tokens) == count


# ---------------------------------------------------------------- stream_chat

class _FakeResponse:
    def __init__(self, tokens, on_first=None):
        self._tokens = tokens
        self._on_first = on_first
        self.closed = False
        self.read_all = False

    def iter_lines(self):
        for i, tok in enumerate(self._tokens):
            if i == 1 and self._on_first:
                self._on_first()
            yield json.dumps({"message": {"content": tok},
                              "done": False}).encode("utf-8")
        self.read_all = True
        yield json.dumps({"message": {"content": ""},
                          "done": True}).encode("utf-8")

    def close(self):
        self.closed = True


def _make_client(resp):
    from core.llm_client import LLMClient
    client = LLMClient.__new__(LLMClient)
    client.config = {"model_mode": "本地路由", "local_model": "fake-model"}
    client.trunk = None
    client.base_url = "http://127.0.0.1:11434"
    client.ollama_down = False
    client._fail_count = 0
    client._model_cooldown = {}
    client._post = lambda url, **kw: resp
    chat_calls = []
    client.chat = lambda msgs: chat_calls.append(msgs) or "不该被调用"
    return client, chat_calls


def test_stream_chat_breaks_on_cancel_and_closes_response():
    token = CancelToken()
    got = []
    resp = _FakeResponse(["甲", "乙", "丙", "丁"], on_first=token.cancel)
    client, chat_calls = _make_client(resp)

    answer = client.stream_chat("说点什么", on_token=got.append,
                                cancel_token=token)

    assert answer == "甲", "取消后应当保留已收到的内容并立刻停止"
    assert got == ["甲"], "取消后不应继续回调 token"
    assert resp.closed is True, "流响应没有被关闭，Ollama 锁会一直被占用"
    assert resp.read_all is False, "取消后不应把整个流读完"
    assert chat_calls == [], "取消后不应再走非流式兜底重试"


def test_stream_chat_not_cancelled_still_reads_everything():
    token = CancelToken()
    got = []
    resp = _FakeResponse(["甲", "乙"])
    client, _ = _make_client(resp)

    answer = client.stream_chat("说点什么", on_token=got.append,
                                cancel_token=token)

    assert answer == "甲乙"
    assert got == ["甲", "乙"]
    assert resp.read_all is True


def test_stream_chat_cancelled_before_start_does_nothing():
    token = CancelToken()
    token.cancel()
    resp = _FakeResponse(["甲"])
    client, chat_calls = _make_client(resp)

    assert client.stream_chat("你好", cancel_token=token) == ""
    assert resp.closed is False
    assert chat_calls == []


def test_cancel_token_swallows_bad_closers():
    token = CancelToken()

    def boom():
        raise RuntimeError("close failed")

    token.bind(boom)
    token.bind(None)          # 不可调用：直接忽略
    token.cancel()
    assert token.is_cancelled() is True


def test_cancel_token_late_closer_error_is_swallowed():
    token = CancelToken()
    token.cancel()

    def boom():
        raise RuntimeError("late close failed")

    token.bind(boom)          # 已取消后再绑定：立即执行，异常不外抛
    assert token.is_cancelled() is True


def test_stream_chat_skips_blank_and_broken_lines():
    lines = [json.dumps({"message": {"content": "好"}}).encode("utf-8"),
             b"", b"not-json",
             json.dumps({"message": {"content": "的"}, "done": True}).encode("utf-8")]
    resp = _FakeResponse([])
    resp.iter_lines = lambda: iter(lines)
    client, _ = _make_client(resp)

    assert client.stream_chat("说点什么", on_token=lambda _t: None) == "好的"


def test_stream_chat_cloud_mode_cancelled_returns_without_tokens():
    token = CancelToken()
    client, _ = _make_client(_FakeResponse([]))
    client.config["model_mode"] = "云端模型"
    got = []

    def cloud(_msg):
        token.cancel()
        return "云答案"

    client._try_cloud = cloud
    assert client.stream_chat("hi", on_token=got.append,
                              cancel_token=token) == "云答案"
    assert got == []


def test_stream_chat_force_cloud_model_cancelled():
    token = CancelToken()
    client, _ = _make_client(_FakeResponse([]))
    got = []

    def cloud(_msg):
        token.cancel()
        return "云答案"

    client._try_cloud = cloud
    assert client.stream_chat("hi", on_token=got.append,
                              force_model="__cloud__",
                              cancel_token=token) == "云答案"
    assert got == []


def test_stream_chat_read_timeout_when_cancelled_returns_partial():
    import requests
    token = CancelToken()
    client, chat_calls = _make_client(_FakeResponse([]))

    def post(*_a, **_k):
        token.cancel()
        raise requests.exceptions.ReadTimeout("timeout")

    client._post = post
    assert client.stream_chat("hi", cancel_token=token) == ""
    assert chat_calls == []


def test_stream_chat_connection_error_when_cancelled_returns_partial():
    import requests
    token = CancelToken()
    client, chat_calls = _make_client(_FakeResponse([]))

    def post(*_a, **_k):
        token.cancel()
        raise requests.exceptions.ConnectionError("reset")

    client._post = post
    assert client.stream_chat("hi", cancel_token=token) == ""
    assert chat_calls == []


def test_stream_chat_transport_error_after_cancel_returns_partial():
    """取消导致 iter_lines 抛异常：按"已取消"处理，不当作模型错误。"""
    token = CancelToken()

    class _Exploding:
        def iter_lines(self):
            token.cancel()
            raise ValueError("socket closed")

        def close(self):
            return None

    client, chat_calls = _make_client(_Exploding())
    assert client.stream_chat("hi", cancel_token=token) == ""
    assert chat_calls == []


def test_stream_chat_selection_error_after_cancel_returns_partial():
    token = CancelToken()
    client, chat_calls = _make_client(_FakeResponse([]))

    def pick(_msg):
        token.cancel()
        raise RuntimeError("bad model")

    client._pick_model = pick
    assert client.stream_chat("hi", cancel_token=token) == ""
    assert chat_calls == []


def test_stream_chat_close_failure_is_swallowed():
    resp = _FakeResponse(["甲"])

    def close():
        raise RuntimeError("close failed")

    resp.close = close
    client, _ = _make_client(resp)
    assert client.stream_chat("hi", on_token=lambda _t: None) == "甲"


def test_stream_chat_unexpected_error_is_reported():
    client, _ = _make_client(_FakeResponse([]))
    got = []

    def post(*_a, **_k):
        raise ValueError("boom")

    client._post = post
    assert client.stream_chat("hi", on_token=got.append) == ""
    assert got and "模型错误" in got[0]


# ---------------------------------------------------------------- dispatcher

def test_dispatcher_does_not_retry_when_cancelled():
    from core.pipeline.llm_dispatcher import LLMDispatcher

    class _LLM:
        def __init__(self):
            self.chat_calls = []

        def stream_chat(self, messages, on_token=None, cancel_token=None):
            if on_token:
                on_token("半句")
            return ""

        def chat(self, messages):
            self.chat_calls.append(messages)
            return "完整回复"

    class _Trunk:
        def __init__(self, llm):
            self.modules = {"llm": llm}

    llm = _LLM()
    dispatcher = LLMDispatcher(_Trunk(llm))
    token = CancelToken()
    token.cancel()

    answer = dispatcher.dispatch([{"role": "user", "content": "hi"}],
                                 on_token=lambda _t: None,
                                 cancel_token=token)

    assert answer == ""
    assert llm.chat_calls == [], "取消后不应再打一次非流式模型"
