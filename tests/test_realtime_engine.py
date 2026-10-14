# -*- coding: utf-8 -*-
"""实时语音对话引擎（core/realtime/engine.py）

为什么补这个文件
----------------
工程化方案实测它 **0% 覆盖**（184 条语句）。它是"实时对话"这条链路的
总调度：采集 → VAD → ASR → LLM → TTS → 播放，五个线程靠事件总线串起来。

它的特点是**强依赖外部世界**（麦克风、pyaudio、语音模型），
所以原来没测 —— 但这恰恰是最该测的：
    · 缺依赖时给出的话对不对（用户看不到"少个包"，只看到"点了没反应"）
    · 状态机（IDLE/LISTENING/…）会不会卡在中间态
    · 停止/清理会不会留垃圾（临时目录、线程、rounds 表）
这些都**不需要真麦克风**就能验。

本文件全部用假件（假 pyaudio / 假 ASR / 假 TTS），不碰真设备。
"""
import os
import sys
import threading
import time

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))

from core.realtime import engine as E              # noqa: E402
from core.realtime.bus import EventBus             # noqa: E402


class FakeTrunk:
    def __init__(self):
        self.base = BASE
        self.replied = []
        self.status = []

    def reply(self, text, on_token=None):
        self.replied.append(text)
        if on_token:
            on_token("回")
            on_token("答")
        return "回答"

    def _log(self, m):
        pass

    def _set_status(self, m):
        self.status.append(m)


@pytest.fixture
def eng():
    """一个不碰真设备的引擎（子件全换成假的）"""
    t = FakeTrunk()
    e = E.RealtimeEngine(t)
    # 换掉会碰硬件/网络的三件
    e.player = _FakePlayer(e)
    e.asr = _FakeASR()
    e.tts = _FakeTTS()
    return e


class _FakePlayer:
    def __init__(self, eng):
        self.eng = eng
        self.started = False
        self.stopped = False
        self.gen = 1

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def current_gen(self):
        return self.gen

    def play(self, path, gen=0):
        return True


class _FakeASR:
    def warmup(self):
        pass

    def transcribe_frames(self, frames, sr=16000):
        return {"text": "你好"}


class _FakeTTS:
    voice = "v"

    def synthesize(self, text, tag=""):
        return "/tmp/x.mp3"


# ══════════════════════════════════════════════════════════════
# ① 构造与状态机
# ══════════════════════════════════════════════════════════════
def test_construct_sets_idle(eng):
    assert eng.state() == "IDLE"
    assert eng._running is False


def test_frame_size_from_sample_rate(eng):
    """帧长要按采样率算对 —— 算错了 VAD 的时长判断全歪"""
    assert eng.sr == 16000
    assert eng.frame_size == int(16000 * 30 / 1000) == 480


def test_set_state_emits_only_on_change():
    """状态**变了才发事件** —— 否则界面会被重复事件刷爆"""
    got = []
    e = E.RealtimeEngine(FakeTrunk(), on_event=lambda k, d: got.append((k, d)))
    e.player = _FakePlayer(e)
    n0 = len([g for g in got if g[0] == "state"])
    e._set_state("IDLE")                       # 本来就是 IDLE，不该发
    assert len([g for g in got if g[0] == "state"]) == n0, "重复状态也发了事件"
    e._set_state("LISTENING")
    assert e.state() == "LISTENING"
    assert any(g[0] == "state" and g[1].get("state") == "LISTENING"
               for g in got), got


def test_emit_goes_through_bus():
    got = []
    e = E.RealtimeEngine(FakeTrunk(), on_event=lambda k, d: got.append((k, d)))
    e._emit("volume", {"rms": 0.5})
    assert ("volume", {"rms": 0.5}) in got


def test_bus_subscribe_and_unsubscribe():
    """事件总线要能订能退（退不掉会越攒越多）"""
    b = EventBus()
    got = []
    b.subscribe("x", lambda k, d: got.append(d))
    b.emit("x", {"a": 1})
    assert got == [{"a": 1}]
    # 通配
    b2 = EventBus()
    allk = []
    b2.subscribe("*", lambda k, d: allk.append(k))
    b2.emit("y", {})
    assert allk == ["y"]


# ══════════════════════════════════════════════════════════════
# ② start —— **缺依赖时的提示**（这条最要紧）
# ══════════════════════════════════════════════════════════════
def test_start_twice_is_refused(eng):
    eng._running = True
    r = eng.start()
    assert r["ok"] is False and "已在运行" in r["msg"]


def test_start_without_numpy_gives_readable_message(eng, monkeypatch):
    monkeypatch.setattr(E, "np", None)
    r = eng.start()
    assert r["ok"] is False
    assert "numpy" in r["msg"]


def test_start_without_pyaudio_gives_install_hint(eng, monkeypatch):
    """⚠️ 缺 pyaudio 时要给**能照着做**的提示

    用户看到的不是"少个包"，而是"点了没反应"。
    所以这条提示必须带：装什么、怎么装（而且是国内源）。
    """
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "pyaudio":
            raise ImportError("No module named 'pyaudio'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    r = eng.start()
    assert r["ok"] is False
    assert "pyaudio" in r["msg"]
    # v25.2.11 统一要求：提示必须带国内源
    assert "tuna.tsinghua" in r["msg"], \
        "提示没带国内源 —— 用户跑会走 PyPI 官方源，国内很慢：%s" % r["msg"]


# ══════════════════════════════════════════════════════════════
# ③ stop / 清理
# ══════════════════════════════════════════════════════════════
def test_stop_before_start_does_not_crash(eng):
    """⚠️ 没启动就点停止不能崩（用户会乱点）"""
    r = eng.stop()
    assert r["ok"] is True
    assert eng.state() == "IDLE"
    assert eng._running is False


def test_stop_is_idempotent(eng):
    for _ in range(3):
        assert eng.stop()["ok"] is True


def test_cleanup_removes_temp_dir(eng):
    """⚠️ 临时目录必须删掉

    实时对话会往临时目录写录音和合成的音频 —— 不删的话
    每次用都留一堆文件在系统 temp 里，而且**用户不知道去哪清**。
    """
    tmp = eng._tmp
    assert os.path.isdir(tmp), "构造时没建临时目录"
    eng.cleanup()
    assert not os.path.exists(tmp), "cleanup 没删掉临时目录: %s" % tmp


def test_cleanup_twice_is_safe(eng):
    eng.cleanup()
    eng.cleanup()                              # 不许抛


def test_cleanup_survives_missing_dir(eng):
    import shutil
    shutil.rmtree(eng._tmp, ignore_errors=True)
    eng.cleanup()                              # 目录已经不在了也不许抛


def test_set_voice(eng):
    eng.set_voice("zh-CN-YunxiNeural")
    assert eng.tts.voice == "zh-CN-YunxiNeural"


# ══════════════════════════════════════════════════════════════
# ④ 轮次跟踪 —— 防泄漏
# ══════════════════════════════════════════════════════════════
def test_on_play_end_clears_round(eng):
    """⚠️ 播完要把这一轮从 `_rounds` 里摘掉

    不摘的话这张表会随对话一直涨 —— 长时间开着实时对话
    （它的设计就是常开）内存会慢慢被吃光，而且**很难查**：
    表面上是"用久了变卡"。
    """
    rid = 123
    eng._rounds[rid] = {"gen": 7}
    eng._on_play_end(7)
    assert rid not in eng._rounds, \
        "播完了但轮次没清：%s" % eng._rounds


def test_on_play_end_keeps_other_gens(eng):
    """只清**同一代**的 —— 上一代的残留不该误伤正在播的"""
    eng._rounds[1] = {"gen": 7}
    eng._rounds[2] = {"gen": 8}
    eng._on_play_end(7)
    assert 1 not in eng._rounds
    assert 2 in eng._rounds, "把别的代也清了"


def test_on_play_end_with_no_rounds(eng):
    eng._on_play_end(999)                      # 不许抛


def test_on_play_start_emits(eng):
    got = []
    eng.bus.subscribe("*", lambda k, d: got.append(k))
    eng._on_play_start(1, "/tmp/a.mp3")
    assert isinstance(got, list)               # 至少不许抛


# ══════════════════════════════════════════════════════════════
# ⑤ 一轮完整对话（假件驱动）
# ══════════════════════════════════════════════════════════════
def test_handle_round_calls_trunk_reply(eng):
    eng._handle_round([b"\x00" * 960])
    assert eng.trunk.replied == ["你好"], eng.trunk.replied


def test_handle_round_ignores_empty_text(eng):
    """⚠️ ASR 没听清（空文本）时**不能**拿空字符串去问模型

    那会让模型对着空白瞎答，用户看到的是"它突然自言自语"。
    """
    eng.asr.transcribe_frames = lambda frames, sr=0: {"text": "   "}
    eng._handle_round([b"\x00" * 960])
    assert eng.trunk.replied == [], "空文本也发给模型了"


def test_handle_round_survives_asr_error(eng):
    """ASR 抛异常不能把线程带死（它跑在采集线程里）"""
    def boom(frames, sr=0):
        raise RuntimeError("识别炸了")
    eng.asr.transcribe_frames = boom
    eng._handle_round([b"\x00" * 960])         # 不许抛出去


def test_handle_round_survives_reply_error(eng):
    """模型回复抛异常也不能带死线程"""
    def boom(text, on_token=None):
        raise RuntimeError("模型炸了")
    eng.trunk.reply = boom
    eng._handle_round([b"\x00" * 960])         # 不许抛出去


def test_handle_round_queues_tts(eng):
    """回复要进 TTS 队列（否则只出字不出声）"""
    eng._tts_q = __import__("queue").Queue()
    eng._handle_round([b"\x00" * 960])
    assert not eng._tts_q.empty(), "没把回复排进 TTS 队列"


# ══════════════════════════════════════════════════════════════
# ⑥ 线程安全
# ══════════════════════════════════════════════════════════════
def test_state_lock_under_concurrency(eng):
    """多线程同时改状态不能崩（采集/ASR/TTS 三个线程都会改它）"""
    errs = []

    def worker():
        try:
            for _ in range(200):
                eng._set_state("LISTENING")
                eng._set_state("IDLE")
                eng.state()
        except Exception as e:
            errs.append(e)

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert not errs, "并发改状态出错了：%s" % errs[:2]
    assert eng.state() in ("IDLE", "LISTENING")


def test_on_play_end_lock_under_concurrency(eng):
    """播放在别的线程回调 —— 清轮次要和主线程加轮次互斥"""
    errs = []

    def add():
        try:
            for i in range(200):
                with eng._rounds_lock:
                    eng._rounds[i] = {"gen": i % 3}
        except Exception as e:
            errs.append(e)

    def clear():
        try:
            for _ in range(200):
                eng._on_play_end(1)
        except Exception as e:
            errs.append(e)

    ts = [threading.Thread(target=add), threading.Thread(target=clear)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)
    assert not errs, errs[:2]


# ══════════════════════════════════════════════════════════════
# ⑦ 结构守卫：**每个后台线程都必须是"打不死"的**
# ══════════════════════════════════════════════════════════════
def test_all_loops_wrap_whole_body_in_try():
    """⚠️ 每个 `*_loop` 的 while 体必须**整体**在 try 里

    这条是本文件最有价值的一条。2026-10-14 实测发现四个循环**全中**：
        _capture_loop   只有 stream.read 在 try 里，VAD/numpy/emit 裸着
        _asr_llm_loop   asr.transcribe_frames() 在 try **外面**
        _tts_loop       队列取之后到 synthesize 之前那几行裸着
        _idle_loop      **一行 try 都没有**

    后果有多严重：
        · 后台线程一死，**没有任何提示** —— 界面上状态还是 LISTENING
          或者麦克风灯还亮着，用户只看到"它不理我了"
        · 只能关掉重开（重启线程）
        · 而 `_emit()` 会调**用户的回调**、VAD 会碰音频数据、
          TTS 走网络 —— 都是会抛的地方

    原则：**工作线程绝不该被未处理异常杀死。**

    这条用 AST 检查（不真跑线程 —— 那样测不出"将来有人加了裸代码"）。
    """
    import ast
    src = open(os.path.join(BASE, "core", "realtime", "engine.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)

    problems = []
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or \
                not node.name.endswith("_loop"):
            continue
        found += 1
        loops = [x for x in ast.walk(node) if isinstance(x, ast.While)]
        if not loops:
            continue
        body = loops[0].body
        # 允许两种形状：整体一个 Try；或者 Try + 少量无害语句
        if not isinstance(body[0], ast.Try):
            problems.append("%s: while 体第一条不是 try（是 %s）"
                            % (node.name, type(body[0]).__name__))
    assert found >= 4, "只找到 %d 个 *_loop，是不是改名了？" % found
    assert not problems, (
        "这些后台循环没有整体包 try —— 抛一次异常线程就死了，"
        "而用户**看不到任何提示**：\n  %s" % "\n  ".join(problems))


def test_handle_round_guards_asr_separately():
    """`_handle_round` 里 ASR 那一段也要自己兜住

    光靠外层循环兜住能"线程不死"，但状态会卡在 THINKING
    （界面显示"正在思考"，其实是识别炸了）。所以要单独兜 + 回监听态。
    """
    import ast
    src = open(os.path.join(BASE, "core", "realtime", "engine.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_round":
            # 找 transcribe_frames 那一条语句，它必须在某个 Try 里
            first = node.body[0]
            assert isinstance(first, ast.Try), \
                "_handle_round 第一句不是 try —— ASR 调用又裸了"
            inner = ast.dump(first)
            assert "transcribe_frames" in inner, \
                "try 里没有 transcribe_frames"
            return
    pytest.fail("找不到 _handle_round")


# ══════════════════════════════════════════════════════════════
# ⑧ start 的正常路径（假 pyaudio 驱动）
# ══════════════════════════════════════════════════════════════
class _FakePA:
    paInt16 = 8

    def open(self, **kw):
        return _FakeStream()

    def terminate(self):
        pass


class _FakeStream:
    def __init__(self):
        self.closed = False

    def read(self, n, exception_on_overflow=False):
        time.sleep(0.01)
        return b"\x00" * (n * 2)

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


def test_start_success_sets_listening(eng, monkeypatch):
    """正常启动：要起线程、回监听态、返回设备号"""
    import types
    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = _FakePA
    monkeypatch.setitem(sys.modules, "pyaudio", fake)

    e = E.RealtimeEngine(FakeTrunk())
    e.player = _FakePlayer(e)
    e.asr = _FakeASR()
    e.tts = _FakeTTS()
    try:
        r = e.start()
        assert r["ok"] is True, r
        assert e.state() == "LISTENING"
        assert e._running is True
        assert e.player.started is True            # player 要起
        assert isinstance(eng.device_index, int)
    finally:
        e._running = False                          # 让线程自己退
        e.cleanup()


def test_start_opens_microphone_with_right_params(eng, monkeypatch):
    """麦克风参数要按采样率/帧长算对 —— 算错了录出来的音频全是噪音"""
    import types
    seen = {}

    class PA2(_FakePA):
        def open(self, **kw):
            seen.update(kw)
            return _FakeStream()

    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = PA2
    monkeypatch.setitem(sys.modules, "pyaudio", fake)

    e = E.RealtimeEngine(FakeTrunk(), sample_rate=16000, frame_ms=30)
    e.player = _FakePlayer(e)
    e.asr = _FakeASR()
    e.tts = _FakeTTS()
    try:
        e.start()
        assert seen.get("rate") == 16000, seen
        assert seen.get("frames_per_buffer") == 480, seen
        assert seen.get("channels") == 1, seen
        assert seen.get("input") is True, seen
    finally:
        e._running = False
        e.cleanup()


def test_start_reports_microphone_failure(eng, monkeypatch):
    """⚠️ 打不开麦克风要**明确报出来**

    常见原因：被别的程序占用、没插麦、驱动不对。
    不报的话用户看到的是"点了启动但什么都没发生"。
    """
    import types

    class PA3(_FakePA):
        def open(self, **kw):
            raise OSError("设备被占用")

    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = PA3
    monkeypatch.setitem(sys.modules, "pyaudio", fake)

    e = E.RealtimeEngine(FakeTrunk())
    e.player = _FakePlayer(e)
    e.asr = _FakeASR()
    e.tts = _FakeTTS()
    got = []
    e.bus.subscribe("*", lambda k, d: got.append((k, d)))
    try:
        e.start()
        errs = [d for k, d in got if k == "error"]
        assert errs, "打不开麦克风却没报错：%s" % got
        assert "麦克风" in errs[0]["msg"], errs
        assert e._running is False, "失败了还把 running 设成 True"
    finally:
        e.cleanup()


def test_capture_loop_feeds_asr_queue(eng, monkeypatch):
    """采集循环要把识别结果排进 ASR 队列（这是整条链路的入口）"""
    import types
    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = _FakePA
    monkeypatch.setitem(sys.modules, "pyaudio", fake)

    e = E.RealtimeEngine(FakeTrunk())
    e.player = _FakePlayer(e)
    e.asr = _FakeASR()
    e.tts = _FakeTTS()
    # 让 VAD 第一次就报 end（模拟"说完一句"）
    e.vad.process = lambda d: "end"
    e._rec_buf = [b"\x00" * 960]
    e._pa = _FakePA()
    e.emit_volume = False
    e._running = True

    t = threading.Thread(target=e._capture_loop, daemon=True)
    t.start()
    deadline = time.time() + 3
    got = False
    while time.time() < deadline:
        if not e._asr_q.empty():
            got = True
            break
        time.sleep(0.02)
    e._running = False
    t.join(timeout=3)
    try:
        assert got, "采集循环没往 ASR 队列里放东西"
    finally:
        e.cleanup()


def test_idle_loop_returns_immediately_when_disabled(eng):
    """idle_stop_sec=0 时不该起这个循环（省一个常驻线程）"""
    eng.idle_stop_sec = 0
    t0 = time.time()
    eng._idle_loop()                           # 该立刻返回
    assert time.time() - t0 < 1.0
