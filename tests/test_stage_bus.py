# -*- coding: utf-8 -*-
"""过程可见（第 5 批 A4 + 深度⑥⑦⑧）：事件总线、单步取消、进度 ETA。

全部离线：不调模型、不联网、不碰 Qt。
"""
import pytest

from core.pipeline import stage_bus as bus
from core.pipeline.post_processor import PostProcessor
from core.pipeline.reply_pipeline import ReplyPipeline


@pytest.fixture(autouse=True)
def _clean_bus():
    bus.reset()
    yield
    bus.reset()


class FakeTrunk:
    def __init__(self, base=".", rules=None):
        self.base = str(base)
        self.config = {}
        self.rules = rules or {}
        self.modules = {}
        self._reply_n = 1
        self.mem = []

    def rule(self, key, default=None):
        return self.rules.get(key, default)

    def mem_recent(self, n=6):
        return []

    def mem_add(self, u, a):
        self.mem.append((u, a))

    def _load_lazy(self, name):
        return None

    def _log(self, msg):
        pass

    def _set_status(self, text):
        pass


# ------------------------------------------------------------------ 订阅/广播
def test_emit_delivers_to_subscribers():
    got = []
    bus.subscribe(lambda e, p: got.append((e, p)))
    data = bus.emit("stage", {"stage": "接收消息", "status": "ok"})
    assert got and got[0][0] == "stage"
    assert got[0][1]["stage"] == "接收消息"
    assert data["seq"] == 1


def test_unsubscribe_stops_delivery():
    got = []
    cb = lambda e, p: got.append(e)      # noqa: E731
    bus.subscribe(cb)
    bus.emit("stage", {"stage": "a"})
    assert bus.unsubscribe(cb) is True
    bus.emit("stage", {"stage": "b"})
    assert len(got) == 1
    # 重复退订不报错
    assert bus.unsubscribe(cb) is False


def test_duplicate_subscribe_is_ignored():
    cb = lambda e, p: None      # noqa: E731
    bus.subscribe(cb)
    bus.subscribe(cb)
    assert bus.subscriber_count() == 1


def test_broken_subscriber_does_not_break_others():
    got = []

    def boom(event, payload):
        raise RuntimeError("订阅者坏了")

    bus.subscribe(boom)
    bus.subscribe(lambda e, p: got.append(e))
    bus.emit("stage", {"stage": "接收消息"})
    assert got == ["stage"]


def test_snapshot_and_clear_events():
    bus.emit("stage", {"stage": "a"})
    bus.emit("stage", {"stage": "b"})
    assert [r["stage"] for r in bus.snapshot(2)] == ["a", "b"]
    bus.clear_events()
    assert bus.snapshot() == []


# ------------------------------------------------------------------ 进度 / ETA
def test_progress_starts_at_zero():
    progress = bus.begin_run(total=4)
    snap = progress.snapshot()
    assert snap["percent"] == 0.0
    assert snap["total"] == 4


def test_progress_advances_and_estimates_eta():
    progress = bus.Progress(total=4, now=0)
    progress.finish(seconds=2, now=2)
    progress.finish(seconds=2, now=4)
    snap = progress.snapshot(now=4)
    assert snap["percent"] == 0.5
    assert snap["done"] == 2
    assert snap["eta"] == 4.0          # 平均 2 秒 × 剩余 2 步


def test_progress_eta_can_be_disabled():
    progress = bus.Progress(total=3, eta=False, now=0)
    progress.finish(seconds=1, now=1)
    snap = progress.snapshot(now=1)
    assert "eta" not in snap
    assert snap["percent"] == pytest.approx(0.333, abs=0.01)


def test_progress_never_exceeds_total():
    progress = bus.Progress(total=1, now=0)
    progress.finish(seconds=1, now=1)
    progress.finish(seconds=1, now=2)
    snap = progress.snapshot(now=2)
    assert snap["percent"] == 1.0
    assert snap["done"] == 1


def test_stage_payload_carries_progress():
    bus.begin_run(total=2)
    payload = bus.stage("接收消息", status="running")
    assert payload["percent"] == 0.0
    assert payload["total"] == 2
    assert "eta" in payload


# -------------------------------------------------------------- 步骤与单步取消
def test_begin_step_emits_running():
    step = bus.begin_step("接收消息", detail="你好")
    rows = bus.events_by_kind("stage")
    assert rows[-1]["stage"] == "接收消息"
    assert rows[-1]["status"] == "running"
    assert rows[-1]["step"] == step.sid


def test_end_step_marks_ok_and_advances():
    bus.begin_run(total=2)
    step = bus.begin_step("组装上下文")
    payload = bus.end_step(step, "ok", "简单=True")
    assert payload["status"] == "ok"
    assert payload["detail"] == "简单=True"
    assert payload["percent"] == 0.5
    assert step.status == "ok"


def test_skipped_step_does_not_advance_progress():
    bus.begin_run(total=2)
    step = bus.begin_step("模型生成")
    payload = bus.end_step(step, "skipped", "用户中断")
    assert payload["status"] == "skipped"
    assert payload["percent"] == 0.0


def test_cancel_step_calls_hook_and_marks_cancelled():
    called = []
    step = bus.begin_step("模型生成", on_cancel=lambda: called.append(True))
    assert bus.cancel_step(step.sid) is True
    assert called == [True]
    assert step.cancelled is True
    assert bus.events_by_kind("stage")[-1]["status"] == "cancelled"


def test_cancel_finished_step_returns_false():
    step = bus.begin_step("接收消息")
    bus.end_step(step, "ok")
    assert bus.cancel_step(step.sid) is False


def test_cancel_unknown_step_returns_false():
    assert bus.cancel_step("不存在") is False


def test_end_step_keeps_cancelled_status():
    step = bus.begin_step("模型生成")
    bus.cancel_step(step)
    payload = bus.end_step(step, "ok")
    assert payload["status"] == "cancelled"


def test_running_step_points_at_latest_running():
    first = bus.begin_step("一")
    bus.end_step(first, "ok")
    second = bus.begin_step("二")
    assert bus.running_step() is second
    bus.end_step(second, "ok")
    assert bus.running_step() is None


# ----------------------------------------------------------------- 工具事件
def test_tool_call_and_result_events():
    bus.tool_call("code_runner", {"代码行数": 3})
    bus.tool_result("code_runner", True, "运行成功 42", ms=820)
    calls = bus.events_by_kind("tool_call")
    results = bus.events_by_kind("tool_result")
    assert calls[-1]["tool"] == "code_runner"
    assert calls[-1]["args"]["代码行数"] == 3
    assert results[-1]["ok"] is True
    assert results[-1]["ms"] == 820


def test_post_processor_emits_tool_events(tmp_path):
    class Runner:
        def run(self, code, timeout=8):
            return {"成功": True, "输出": "42", "错误": ""}

    trunk = FakeTrunk(tmp_path)
    trunk._load_lazy = lambda name: Runner() if name == "code_runner" else None
    pp = PostProcessor(trunk)
    answer = pp.verify_code("帮我跑一下代码", "```python\nprint(42)\n```")
    assert "沙盒验证运行成功" in answer
    assert bus.events_by_kind("tool_call")
    assert bus.events_by_kind("tool_result")[-1]["ok"] is True


# ------------------------------------------------------------------- 文案工具
def test_circled_wraps_after_ten():
    assert bus.circled(0) == "①"
    assert bus.circled(9) == "⑩"
    assert bus.circled(10) == "11."


def test_format_line_running_shows_eta():
    line = bus.format_line({"stage": "模型生成", "status": "running",
                            "percent": 0.5, "eta": 6.0})
    assert "模型生成" in line and "50%" in line and "预计还需 6 秒" in line


def test_format_line_ok_shows_cost():
    line = bus.format_line({"stage": "模型生成", "status": "ok", "ms": 1500})
    assert "✓" in line and "1.5 秒" in line


def test_format_events_mixes_tools_and_stages():
    bus.stage("接收消息", status="ok")
    bus.tool_call("code_runner", {"代码行数": 3})
    bus.tool_result("code_runner", False, "SyntaxError", ms=500)
    text = bus.format_events()
    assert "接收消息" in text
    assert "调用 code_runner" in text
    assert "SyntaxError" in text


# ------------------------------------------------------------------ 管线接线
def _pipeline(tmp_path, rules=None):
    trunk = FakeTrunk(tmp_path, rules=rules)
    pipe = ReplyPipeline(trunk)
    pipe.ld.dispatch = lambda messages, on_token=None, cancel_token=None: "好呀。"
    pipe.pp.kick_off_background = lambda u, a: None
    return pipe


def test_pipeline_run_emits_all_stages(tmp_path):
    rules = {"聊天.状态层": "off", "聊天.规划器": "off", "聊天.校验器": "off",
             "记忆.v2": "off"}
    pipe = _pipeline(tmp_path, rules)
    pipe.ctx.is_simple = lambda text: True
    pipe.ctx.build = lambda text, simple: ""
    pipe.pa.assemble = lambda text, ctx, simple, plan=None, state=None, gray=False: [
        {"role": "user", "content": text}]
    answer = pipe.run("你好")
    assert answer == "好呀。"
    stages = [r["stage"] for r in bus.events_by_kind("stage")]
    for name in ("接收消息", "组装上下文", "拼提示词", "模型生成", "校验收尾"):
        assert name in stages
    assert bus.events_by_kind("stage")[-1]["percent"] > 0


def test_pipeline_stage_off_emits_nothing(tmp_path):
    pipe = _pipeline(tmp_path, {"聊天.过程可见": "off", "聊天.状态层": "off",
                                "聊天.规划器": "off", "聊天.校验器": "off",
                                "记忆.v2": "off"})
    pipe.ctx.is_simple = lambda text: True
    pipe.ctx.build = lambda text, simple: ""
    pipe.pa.assemble = lambda text, ctx, simple, plan=None, state=None, gray=False: []
    pipe.run("你好")
    assert bus.snapshot() == []


def test_pipeline_generation_cancel_skips_tail(tmp_path):
    class Token:
        def __init__(self):
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def is_cancelled(self):
            return self._cancelled

    pipe = _pipeline(tmp_path, {"聊天.状态层": "off", "聊天.规划器": "off",
                                "聊天.校验器": "off", "记忆.v2": "off"})
    pipe.ctx.is_simple = lambda text: True
    pipe.ctx.build = lambda text, simple: ""
    pipe.pa.assemble = lambda text, ctx, simple, plan=None, state=None, gray=False: []
    token = Token()

    def dispatch(messages, on_token=None, cancel_token=None):
        bus.cancel_step(bus.running_step())     # 模拟用户点"取消这一步"
        return "半截回复"

    pipe.ld.dispatch = dispatch
    answer = pipe.run("你好", cancel_token=token)
    assert answer == "半截回复"
    stages = [r["stage"] for r in bus.events_by_kind("stage")]
    assert "校验收尾" not in stages
    assert "用户取消" in stages
    assert token.is_cancelled() is True


def test_pipeline_step_cancel_rule_off_does_not_hook_token(tmp_path):
    class Token:
        def __init__(self):
            self._cancelled = False

        def cancel(self):
            self._cancelled = True

        def is_cancelled(self):
            return self._cancelled

    pipe = _pipeline(tmp_path, {"聊天.单步取消": False, "聊天.状态层": "off",
                                "聊天.规划器": "off", "聊天.校验器": "off",
                                "记忆.v2": "off"})
    pipe.ctx.is_simple = lambda text: True
    pipe.ctx.build = lambda text, simple: ""
    pipe.pa.assemble = lambda text, ctx, simple, plan=None, state=None, gray=False: []
    token = Token()
    pipe.run("你好", cancel_token=token)
    assert token.is_cancelled() is False
