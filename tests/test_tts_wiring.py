# -*- coding: utf-8 -*-
"""自动朗读整条链路：开关 → 配置 → 合成 → 播放。

2026-11-01 用户反馈「自动朗读开了，回复没有声音」。排查下来是两处断链：

1. 加号菜单的开关只翻了一个内存属性 ``_auto_tts``，
   而 ``chat_mixin`` 判断的是 ``trunk.config["auto_tts"]``
   → 菜单提示"已开启"，回复**根本不会朗读**。
2. 语音模块 ``speak()`` 从不返回音频路径，
   ``TTSWorker`` 只能发出空路径 → ``SpeechController.play("")`` 直接 return
   → 静默失败，用户既没声音也没提示。

这组用例把两处都钉住，防止以后又"看着开着、其实没播"。
"""
import asyncio
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.mixins.chat_mixin import ChatMixin  # noqa: E402
from gui.mixins.ui_actions_mixin import UIActionsMixin  # noqa: E402


class _FakeBox:
    """替掉 QMessageBox：测试环境里不能弹模态框。"""

    shown = []

    @staticmethod
    def information(*args, **kwargs):
        _FakeBox.shown.append(("information", str(args[2] if len(args) > 2 else "")))

    @staticmethod
    def warning(*args, **kwargs):
        _FakeBox.shown.append(("warning", str(args[2] if len(args) > 2 else "")))


class _Trunk:
    def __init__(self, config):
        self.config = config
        self.saves = 0
        self.modules = {}

    def save_config(self):
        self.saves += 1

    def rule(self, key, default=None):
        return self.config.get(key, default)


class _Chat:
    def __init__(self):
        self.out = []

    def split_group(self, text):
        return []

    def render_reply(self, text, fallback_name=""):
        self.out.append(str(text))

    def append(self, text):
        self.out.append(str(text))

    def remove_from_anchor(self, anchor):
        return None


class _Account:
    def save_line(self, who, text):
        self.last = (who, text)


class _Speech:
    def __init__(self):
        self.calls = []

    def speak_async(self, text, on_error=None):
        self.calls.append((text, on_error))


class _Host(UIActionsMixin):
    """只带加号菜单那一组方法的最小宿主。"""

    def __init__(self, config):
        self.trunk = _Trunk(config)
        self.chat = _Chat()


class _MiniHost(ChatMixin):
    """跑 ``ChatMixin._on_reply`` 的最小宿主（不建窗口、不连模型）。"""

    ai_name = "小6"

    def __init__(self, config):
        self.trunk = _Trunk(config)
        self.chat = _Chat()
        self.account = _Account()
        self.speech = _Speech()
        self.stage_finished = 0
        self._chat_anchor = None
        self._stream_buf = []
        self._stream_rendered_once = False

    def _stage_finish(self):
        self.stage_finished += 1

    def _reply_failed(self, text):
        return False

    def _mark_guide_event(self, name):
        return None

    def _handle_last_task_result(self):
        return None

    def _update_empty_state(self):
        return None

    def _after_reply_guidance(self, text):
        self.guided = str(text)

    def _maybe_offer_install(self, text):
        return None


# ------------------------------------------------------------ 开关落配置
def test_toggle_writes_config_and_persists(monkeypatch):
    from gui.mixins import ui_actions_mixin as ui

    monkeypatch.setattr(ui, "QMessageBox", _FakeBox)
    host = _Host({})
    host._auto_tts = False
    assert host._auto_tts_enabled() is False
    assert host.toggle_auto_tts() is True
    assert host.trunk.config["auto_tts"] is True, "开关必须写进 config"
    assert host.trunk.saves == 1, "写进 config 后要落盘，重启才记得"
    assert host._auto_tts_enabled() is True
    assert host.toggle_auto_tts() is False
    assert host.trunk.config["auto_tts"] is False
    assert host.trunk.saves == 2


def test_toggle_without_config_warns(monkeypatch):
    from gui.mixins import ui_actions_mixin as ui

    monkeypatch.setattr(ui, "QMessageBox", _FakeBox)
    host = _Host(None)
    host.trunk = None
    assert host.toggle_auto_tts() is False
    assert any(kind == "warning" for kind, _ in _FakeBox.shown)


def test_auto_tts_state_comes_from_config_not_memory():
    """内存属性可能是旧的；以配置为准，避免"菜单说开、实际没开"。"""
    host = _Host({"auto_tts": True})
    host._auto_tts = False
    assert host._auto_tts_enabled() is True
    host.trunk.config["auto_tts"] = False
    host._auto_tts = True
    assert host._auto_tts_enabled() is False


# ------------------------------------------------------------ 回复触发朗读
def test_reply_speaks_when_auto_tts_on():
    mini = _MiniHost({"auto_tts": True})
    mini._on_reply("你好呀，今天想聊点啥？")
    assert len(mini.speech.calls) == 1
    text, on_error = mini.speech.calls[0]
    assert text == "你好呀，今天想聊点啥？"
    assert callable(on_error), "朗读失败必须有回调，否则又变成静默失败"


def test_reply_is_silent_when_auto_tts_off():
    mini = _MiniHost({"auto_tts": False})
    mini._on_reply("你好呀")
    assert mini.speech.calls == []


def test_tts_failure_is_reported_once_within_ten_minutes():
    mini = _MiniHost({"auto_tts": True})
    mini._tts_failed("没装 edge-tts")
    mini._tts_failed("没装 edge-tts")
    hits = [t for t in mini.chat.out if "朗读失败" in t]
    assert len(hits) == 1, "同一原因不该每句回复刷一次"
    assert "没装 edge-tts" in hits[0]


# ------------------------------------------------------------ 合成回传路径
def test_speak_returns_audio_path_for_player(tmp_path, monkeypatch):
    from modules.installed import tts as tts_mod

    engine = tts_mod.TTS(_Trunk({}))
    engine.base = str(tmp_path)
    engine.sandbox = os.path.join(str(tmp_path), "tts")
    os.makedirs(engine.sandbox, exist_ok=True)

    async def fake(text, out_path, params=None, limit_ms=1500):
        with open(out_path, "wb") as f:
            f.write(b"audio-bytes")
        return 10

    opened = []
    monkeypatch.setattr(tts_mod.os, "startfile",
                        lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(engine, "_speak_async", fake)

    out = engine.speak("你好", autoplay=False)
    assert out["ok"] is True
    assert out["path"] and os.path.exists(out["path"]), "必须回传音频路径"
    assert opened == [], "autoplay=False 时不许自己弹播放器（会双重播放）"

    out2 = engine.speak("第二句", autoplay=True)
    assert opened == [out2["path"]]


def test_prune_keeps_only_recent_audio(tmp_path):
    from modules.installed import tts as tts_mod

    engine = tts_mod.TTS(_Trunk({}))
    engine.sandbox = os.path.join(str(tmp_path), "tts")
    os.makedirs(engine.sandbox, exist_ok=True)
    for i in range(8):
        p = os.path.join(engine.sandbox, "xiao6_tts_%d.mp3" % i)
        with open(p, "wb") as f:
            f.write(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    engine._prune(keep=3)
    left = sorted(n for n in os.listdir(engine.sandbox) if n.endswith(".mp3"))
    assert left == ["xiao6_tts_5.mp3", "xiao6_tts_6.mp3", "xiao6_tts_7.mp3"]


# ------------------------------------------------------------ worker 报错
def test_worker_reports_missing_path(tmp_path):
    from gui.workers import TTSWorker

    class _OldTTS:
        def speak(self, text, autoplay=False):
            return {"ok": True}          # 老插件：只说成功，不给路径

    trunk = _Trunk({})
    trunk.base = str(tmp_path)
    trunk._load_lazy = lambda name: _OldTTS() if name == "tts" else None
    done, failed = [], []
    w = TTSWorker(trunk, "你好")
    w.done.connect(done.append)
    w.failed.connect(failed.append)
    w.run()
    assert done == [""]
    assert failed and "音频" in failed[0]


def test_speak_async_wires_player_and_error(monkeypatch):
    from gui import speech as speech_mod

    class _Sig:
        def __init__(self):
            self.fns = []

        def connect(self, fn):
            self.fns.append(fn)

        def emit(self, *args):
            for fn in self.fns:
                fn(*args)

    class _FakeWorker:
        def __init__(self, trunk, text):
            self.text = text
            self.done = _Sig()
            self.failed = _Sig()
            self.finished = _Sig()
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr("gui.workers.TTSWorker", _FakeWorker)
    sc = speech_mod.SpeechController(None, None)
    errors = []
    w = sc.speak_async("你好", on_error=errors.append)
    assert w.started is True
    w.done.emit("")                       # 合成没给出路径
    assert errors and "音频" in errors[0]
    w.failed.emit("没装 edge-tts")
    assert errors[-1] == "没装 edge-tts"
    assert sc._workers == [w], "要保住线程引用，否则没播完就被回收"


# ------------------------------------------------------------ 播放兜底
def test_play_reports_missing_file():
    from gui.speech import SpeechController

    got = []
    sc = SpeechController(None, None)
    assert sc.play("", got.append) is False
    assert got and "音频" in got[0]
    assert sc.play("/no/such/file.mp3", got.append) is False


def test_play_falls_back_to_system_player(tmp_path, monkeypatch):
    from gui.speech import SpeechController

    audio = tmp_path / "reply.mp3"
    audio.write_bytes(b"x")
    opened = []
    monkeypatch.setitem(sys.modules, "PyQt5.QtMultimedia", None)
    monkeypatch.setattr("gui.speech.os.startfile",
                        lambda p: opened.append(p), raising=False)
    sc = SpeechController(None, None)
    assert sc.play(str(audio)) is True
    assert len(opened) == 1, "没有 QtMultimedia 也要用系统播放器出声"


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="os.startfile 只在 Windows 上有")
def test_play_fallback_failure_is_explained(tmp_path, monkeypatch):
    from gui.speech import SpeechController

    audio = tmp_path / "reply.mp3"
    audio.write_bytes(b"x")

    def boom(_p):
        raise OSError("没有关联的播放器")

    got = []
    monkeypatch.setitem(sys.modules, "PyQt5.QtMultimedia", None)
    monkeypatch.setattr("gui.speech.os.startfile", boom)
    sc = SpeechController(None, None)
    assert sc.play(str(audio), got.append) is False
    assert got and "播放失败" in got[0]


# ------------------------------------------------------- 在线失败 → 系统朗读
def _online_tts(tmp_path, rules=None):
    from modules.installed import tts as tts_mod

    engine = tts_mod.TTS(_Trunk(rules or {}))
    engine.sandbox = os.path.join(str(tmp_path), "tts")
    os.makedirs(engine.sandbox, exist_ok=True)
    return engine


def test_offline_voice_keeps_sound_when_edge_tts_fails(tmp_path, monkeypatch):
    """2026-11-01 实测：微软接口整体 403 → 没有第二条路就彻底没声音。"""
    engine = _online_tts(tmp_path)
    wav = os.path.join(engine.sandbox, "local.wav")
    with open(wav, "wb") as f:
        f.write(b"wav")

    async def boom(*a, **k):
        raise RuntimeError("403")

    monkeypatch.setattr(engine, "_speak_async", boom)
    monkeypatch.setattr("core.tts_fallback.speak_to_wav",
                        lambda text, path, voice=None: {"ok": True, "path": wav,
                                                        "error": ""})
    out = engine.speak("你好呀", autoplay=False)
    assert out["ok"] is True
    assert out["path"] == wav
    assert out["engine"] == "系统朗读"
    assert "403" in out["reason"]


def test_offline_voice_can_be_switched_off(tmp_path, monkeypatch):
    engine = _online_tts(tmp_path, {"语音.本地兜底": "off"})

    async def boom(*a, **k):
        raise RuntimeError("403")

    monkeypatch.setattr(engine, "_speak_async", boom)
    out = engine.speak("你好呀")
    assert out["ok"] is False
    assert out["fallback"] == "text"
    assert "403" in out["error"]


def test_offline_failure_reports_both_reasons(tmp_path, monkeypatch):
    engine = _online_tts(tmp_path)

    async def boom(*a, **k):
        raise RuntimeError("403")

    monkeypatch.setattr(engine, "_speak_async", boom)
    monkeypatch.setattr("core.tts_fallback.speak_to_wav",
                        lambda text, path, voice=None: {"ok": False, "path": "",
                                                        "error": "没有中文语音包"})
    out = engine.speak("你好呀")
    assert out["ok"] is False
    assert "403" in out["error"] and "没有中文语音包" in out["error"]


def test_err_text_never_returns_blank():
    """aiohttp 的 WSServerHandshakeError 用 str() 是空串，不能透传成空提示。"""
    from modules.installed import tts as tts_mod

    class _Boom:
        status = 403

        def __str__(self):
            return ""

    assert "403" in tts_mod._err_text(_Boom())
    assert "RuntimeError" in tts_mod._err_text(RuntimeError())
    assert tts_mod._err_text(None)


def test_realtime_tts_falls_back_to_local(tmp_path, monkeypatch):
    from core.realtime import tts as rt

    t = rt.TTS(str(tmp_path))
    wav = tmp_path / "local.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr(t, "_offline", lambda text, out: str(wav))

    def boom(coro):
        coro.close()
        raise RuntimeError("403")

    monkeypatch.setattr(rt.asyncio, "run", boom)
    assert t.synthesize("你好", tag="t") == str(wav)


def test_tts_fallback_module_reports_failures(tmp_path, monkeypatch):
    from core import tts_fallback as fb

    assert fb.speak_to_wav("", tmp_path / "a.wav")["ok"] is False

    class _Proc:
        returncode = 1
        stderr = '<Objs><S S="Error">没有找到语音包_x000D_</S></Objs>'

    monkeypatch.setattr(fb, "_run", lambda script, timeout: _Proc())
    out = fb.speak_to_wav("你好", tmp_path / "b.wav")
    assert out["ok"] is False
    assert "没有找到语音包" in out["error"]


def test_tts_fallback_module_writes_wav(tmp_path, monkeypatch):
    from core import tts_fallback as fb

    wav = tmp_path / "ok.wav"

    class _Proc:
        returncode = 0
        stderr = b""

    def fake_run(script, timeout):
        wav.write_bytes(b"RIFF" + b"\x00" * 100)
        assert "System.Speech" in script
        return _Proc()

    monkeypatch.setattr(fb, "_run", fake_run)
    out = fb.speak_to_wav("你好", wav)
    assert out["ok"] is True and out["path"] == str(wav)
    assert not os.path.exists(str(wav) + ".txt"), "临时文本要清掉"


# ------------------------------------------------------------ 音色切换
def test_voice_comes_from_config():
    """音色以 config["tts_voice"] 为准：改了立刻生效，不用重启模块。"""
    from modules.installed import tts as tts_mod

    engine = tts_mod.TTS(_Trunk({}))
    assert engine._voice() == "zh-CN-XiaoxiaoNeural"
    engine.trunk.config["tts_voice"] = "zh-CN-YunxiNeural"
    assert engine._voice() == "zh-CN-YunxiNeural"
    engine.trunk.config["tts_voice"] = "  "
    assert engine._voice() == "zh-CN-XiaoxiaoNeural", "空值要回落默认"


def test_stats_report_current_voice():
    from modules.installed import tts as tts_mod

    engine = tts_mod.TTS(_Trunk({"tts_voice": "zh-CN-XiaoyiNeural"}))
    assert engine.stats()["声音"] == "zh-CN-XiaoyiNeural"


def test_set_tts_voice_writes_config_and_persists(monkeypatch):
    from gui.mixins import ui_actions_mixin as ui

    monkeypatch.setattr(ui, "QMessageBox", _FakeBox)
    host = _Host({})
    assert host._tts_voice() == "zh-CN-XiaoxiaoNeural"
    assert host._tts_voice_label() == "晓晓（女·温柔）"
    assert host.set_tts_voice("zh-CN-YunjianNeural", "云健（男·有力）") is True
    assert host.trunk.config["tts_voice"] == "zh-CN-YunjianNeural"
    assert host.trunk.saves == 1, "音色也要落盘，重启才记得"
    assert "云健" in _FakeBox.shown[-1][1]
    assert host._tts_voice_label() == "云健（男·有力）"


def test_set_tts_voice_rejects_empty_and_missing_config(monkeypatch):
    from gui.mixins import ui_actions_mixin as ui

    monkeypatch.setattr(ui, "QMessageBox", _FakeBox)
    host = _Host({})
    assert host.set_tts_voice("") is False
    host.trunk = None
    assert host.set_tts_voice("zh-CN-XiaoxiaoNeural") is False
    assert any(kind == "warning" for kind, _ in _FakeBox.shown)


def test_realtime_voice_follows_config():
    """实时对话和朗读共用一个音色：以后只改一处就够。"""
    from core.realtime.tts import TTS

    t = TTS("/tmp")
    assert t.voice == "zh-CN-XiaoxiaoNeural"
    t2 = TTS("/tmp", voice="zh-CN-YunyangNeural")
    assert t2.voice == "zh-CN-YunyangNeural"


def test_speak_cleans_markdown_and_emoji_before_synthesis(tmp_path, monkeypatch):
    """朗读前要洗掉只能看不能读的东西，否则念出来很"假"。"""
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path)
    seen = {}

    async def fake(text, out_path, params=None, limit_ms=3000):
        seen["text"] = text
        with open(out_path, "wb") as f:
            f.write(b"audio")
        return 10

    monkeypatch.setattr(engine, "_speak_async", fake)
    out = engine.speak("**搞定**了 😊 见 https://x.io/a \n```py\nprint(1)\n```", autoplay=False)
    assert out["ok"] is True
    said = seen["text"]
    assert "**" not in said and "😊" not in said and "http" not in said
    assert "print" not in said, "代码块不能念出来"
    assert "搞定" in said


def test_empty_after_cleaning_is_not_sent(tmp_path, monkeypatch):
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path)
    called = []

    async def fake(*a, **k):
        called.append(a)
        return 1

    monkeypatch.setattr(engine, "_speak_async", fake)
    out = engine.speak("😊🎉  ```py\nprint(1)\n```", autoplay=False)
    assert out["ok"] is False and "可朗读" in out["error"]
    assert called == [], "全是符号时不该发起合成"


def test_preview_reads_current_voice_sample():
    """试听：直接出声，不用等下一条回复。"""
    from gui.mixins import ui_actions_mixin as ui

    host = _Host({"tts_voice": "zh-CN-YunxiNeural"})
    host.speech = _Speech()
    host.ai_name = "小6"
    assert host.preview_tts_voice() is True
    text, _on_error = host.speech.calls[0]
    assert "云希" in text, "试听要说当前音色的名字"
    assert any("试听音色" in t for t in host.chat.out)


def test_preview_without_speech_warns(monkeypatch):
    from gui.mixins import ui_actions_mixin as ui

    monkeypatch.setattr(ui, "QMessageBox", _FakeBox)
    host = _Host({})
    host.ai_name = "小6"
    assert host.preview_tts_voice() is False
    assert any(kind == "warning" for kind, _ in _FakeBox.shown)


# ---------------------------------------------- 首包预算只约束首包（2026-11-01）
def _fake_edge_tts(first_delay, chunk_delay, chunks=3):
    """假 edge_tts：首包慢、后续分块也慢，用来复现"整段被首包预算砍掉"。"""

    class _Unused:
        pass

    class _Com:
        def __init__(self, text, voice, **kw):
            self.text = text
            self.voice = voice
            self.kw = kw

        def stream(self):
            async def _gen():
                await asyncio.sleep(first_delay)
                yield {"type": "audio", "data": b"a" * 8}
                for _ in range(chunks):
                    await asyncio.sleep(chunk_delay)
                    yield {"type": "audio", "data": b"b" * 8}
                yield {"type": "WordBoundary", "offset": 1, "text": "x"}

            return _gen()

    return type("FakeEdge", (), {"Communicate": _Com, "list_voices": staticmethod(_Unused)})


def test_first_packet_budget_does_not_cap_whole_synthesis(tmp_path, monkeypatch):
    """预算只管首包：首包到了之后分块再慢也要写完（否则每句都降级系统朗读）。

    旧实现把 deadline 当"整段总时长"，首包 1.1~1.8 秒就吃掉大半预算，
    后面的分块必然超时 → 用户切了音色却听到系统音色（同一个声音）。
    """
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path)
    monkeypatch.setitem(sys.modules, "edge_tts",
                        _fake_edge_tts(0.05, 0.12, chunks=3))
    out = os.path.join(engine.sandbox, "ok.mp3")
    first_ms = asyncio.run(engine._speak_async("你好", out, limit_ms=150))
    assert first_ms >= 40, "首包时间要如实回传"
    data = open(out, "rb").read()
    assert len(data) == 32, "4 个分块都要写完，不能被首包预算砍掉"


def test_first_packet_slow_reports_timeout(tmp_path, monkeypatch):
    """首包超过预算 → 明确报"首包超时"，而不是 TimeoutError。"""
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path, {"语音.首包上限ms": 100, "语音.情绪": "off"})
    monkeypatch.setitem(sys.modules, "edge_tts",
                        _fake_edge_tts(0.25, 0.01, chunks=1))
    wav = os.path.join(engine.sandbox, "fallback.wav")

    def fake_fallback(text, path, voice=None):
        with open(path, "wb") as f:
            f.write(b"wav")
        return {"ok": True, "path": path, "error": ""}

    monkeypatch.setattr("core.tts_fallback.speak_to_wav", fake_fallback)
    out = engine.speak("你好", autoplay=False)
    assert out["ok"] is True
    assert "首包超时" in out["reason"], out["reason"]
    assert out["engine"] == "系统朗读"


def test_partial_audio_is_deleted_after_fallback(tmp_path, monkeypatch):
    """0 字节 / 断头 mp3 不能留在沙盒里：下次排查会误判"在线成功"。"""
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path)
    wav = os.path.join(engine.sandbox, "fallback.wav")

    async def half_then_boom(text, out_path, params=None, limit_ms=3000):
        with open(out_path, "wb") as f:
            f.write(b"partial")
        raise tts_mod._MidwayTimeout()

    def fake_fallback(text, path, voice=None):
        with open(path, "wb") as f:
            f.write(b"wav")
        return {"ok": True, "path": path, "error": ""}

    monkeypatch.setattr(engine, "_speak_async", half_then_boom)
    monkeypatch.setattr("core.tts_fallback.speak_to_wav", fake_fallback)
    out = engine.speak("你好", autoplay=False)
    left = [n for n in os.listdir(engine.sandbox) if n.endswith(".mp3")]
    assert left == [], "半截 mp3 要删掉"
    assert out["ok"] is True and out["path"] in (
        os.path.join(engine.sandbox, n) for n in os.listdir(engine.sandbox))
    assert "中途卡住" in out["reason"]


def test_fallback_gets_same_voice_as_online(tmp_path, monkeypatch):
    """兜底也必须收到音色：离线至少能按性别做音调近似。"""
    from modules.installed import tts as tts_mod

    engine = _online_tts(tmp_path, {"tts_voice": "zh-CN-YunjianNeural"})
    seen = {}

    def fake_fallback(text, path, voice=None):
        seen["voice"] = voice
        with open(path, "wb") as f:
            f.write(b"wav")
        return {"ok": True, "path": path, "error": ""}

    async def boom(*a, **k):
        raise RuntimeError("403")

    monkeypatch.setattr(engine, "_speak_async", boom)
    monkeypatch.setattr("core.tts_fallback.speak_to_wav", fake_fallback)
    engine.speak("你好", autoplay=False)
    assert seen["voice"] == "zh-CN-YunjianNeural"


# ---------------------------------------------- 老 rules.json 迁移（2026-11-01）
def test_rules_engine_migrates_old_default(tmp_path):
    """老机器里 rules.json 存着旧默认 1500 → 必须跟到新默认 3000。

    不迁移的话：默认值改了等于没改，每句回复都首包超时降级系统朗读。
    """
    import json

    from core.rules_engine import RuleEngine

    class _T:
        base = str(tmp_path)

    base = tmp_path
    rules_dir = base / "data" / "rules"
    rules_dir.mkdir(parents=True)
    payload = {"rules": {"语音.首包上限ms": {
        "组": "语音", "类别": "参数", "描述": "x", "default": 1500,
        "value": 1500}}}
    (rules_dir / "rules.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    eng = RuleEngine(_T())
    rules = {"语音.首包上限ms": eng.get("语音.首包上限ms")}
    assert eng.get("语音.首包上限ms") == 3000
    assert eng.registry["语音.首包上限ms"]["来源"] == "迁移"
    saved = json.loads((rules_dir / "rules.json").read_text(encoding="utf-8"))
    assert saved["rules"]["语音.首包上限ms"]["value"] == 3000, "迁移结果要落盘"


def test_rules_engine_keeps_user_chosen_value(tmp_path):
    """用户真改过的值（不是老默认）不能被动。"""
    import json

    from core.rules_engine import RuleEngine

    class _T:
        base = str(tmp_path)

    rules_dir = tmp_path / "data" / "rules"
    rules_dir.mkdir(parents=True)
    payload = {"rules": {"语音.首包上限ms": {"value": 2000}}}
    (rules_dir / "rules.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    eng = RuleEngine(_T())
    assert eng.get("语音.首包上限ms") == 2000
    assert eng.registry["语音.首包上限ms"]["来源"] == "json"


# ---------------------------------------------- 离线音调近似
def test_pitch_for_voice_maps_gender():
    from core.tts_fallback import pitch_for_voice

    assert pitch_for_voice("zh-CN-XiaoxiaoNeural") == "0st"
    assert pitch_for_voice("zh-CN-liaoning-XiaobeiNeural") == "0st"
    for male in ("zh-CN-YunxiNeural", "zh-CN-YunjianNeural",
                 "zh-CN-YunxiaNeural", "zh-CN-YunyangNeural"):
        assert pitch_for_voice(male) == "-6st"
    assert pitch_for_voice("") == "0st"


def test_speak_to_wav_uses_ssml_for_male_voice(tmp_path, monkeypatch):
    """男声走 SSML 降调（实测 pitch 会改波形），临时 ssml 要清掉。"""
    from core import tts_fallback as fb

    wav = tmp_path / "m.wav"
    seen = {}

    class _Proc:
        returncode = 0
        stderr = b""

    def fake_run(script, timeout):
        seen["script"] = script
        wav.write_bytes(b"RIFF" + b"\x00" * 100)
        return _Proc()

    monkeypatch.setattr(fb, "_run", fake_run)
    out = fb.speak_to_wav("你好", wav, voice="zh-CN-YunxiNeural")
    assert out["ok"] is True
    assert "SpeakSsml" in seen["script"], "男声要走 SSML 分支"
    assert str(wav) + ".ssml" in seen["script"], "脚本要读 ssml 文件"
    assert not os.path.exists(str(wav) + ".ssml"), "ssml 临时文件要清掉"
    assert "-6st" in fb._ssml("你好", fb.pitch_for_voice("zh-CN-YunxiNeural"))
    assert "&amp;" in fb._ssml("a&b", "-6st"), "文本要 XML 转义"


def test_speak_to_wav_female_voice_uses_plain_path(tmp_path, monkeypatch):
    """女声（默认）走原来的纯文本朗读，不引入 SSML 风险。"""
    from core import tts_fallback as fb

    wav = tmp_path / "f.wav"
    seen = {}

    class _Proc:
        returncode = 0
        stderr = b""

    def fake_run(script, timeout):
        seen["script"] = script
        wav.write_bytes(b"RIFF" + b"\x00" * 100)
        return _Proc()

    monkeypatch.setattr(fb, "_run", fake_run)
    out = fb.speak_to_wav("你好", wav, voice="zh-CN-XiaoxiaoNeural")
    assert out["ok"] is True
    assert "SpeakSsml" not in seen["script"]
    assert "$syn.Speak($txt)" in seen["script"]
