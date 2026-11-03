# -*- coding: utf-8 -*-
"""TTS文字转语音模块 - 用edge-tts朗读（批次 48.3 加心境情绪与首包预算）

情绪不是玄学：按当前 mood 调 edge-tts 的 rate / pitch / volume，语气更贴
"开心/低落/慵懒"。``语音.情绪`` off 时完全回到旧行为（只传文本和音色）。

首包预算：``语音.首包上限ms`` 默认 3000。流式合成第一块音频超过预算就
改用系统朗读（``语音.本地兜底`` off 时返回 ``{"ok": False, "fallback": "text"}``）；
调用方应直接显示文本，不要让用户干等。合成成功时返回 ``first_packet_ms``，
供 49.2 性能观察。

音色：以 ``config["tts_voice"]`` 为准（默认 zh-CN-XiaoxiaoNeural），
每次合成现读，用户改完立刻生效、不用重启。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import asyncio
import os
import time

from modules.base import BaseModule
from core.data_paths import data_path

try:
    from core.tts_text import naturalize
except ImportError:  # 老安装里没有 core.tts_text：退化成只截长度
    def naturalize(text, limit=500):
        return str(text or "").strip()[:limit]

# 标准 3.4：模块级只放不可变元组，取值时再转 dict，避免共享可变状态
_EMOTION_ROWS = (
    ("开心", {"rate": "+8%", "pitch": "+10Hz", "volume": "+5%"}),
    ("活泼", {"rate": "+5%", "pitch": "+6Hz", "volume": "+0%"}),
    ("精神", {"rate": "+3%", "pitch": "+4Hz", "volume": "+0%"}),
    ("轻松", {"rate": "+0%", "pitch": "+2Hz", "volume": "+0%"}),
    ("慵懒", {"rate": "-8%", "pitch": "-4Hz", "volume": "-5%"}),
    ("低落", {"rate": "-10%", "pitch": "-8Hz", "volume": "-5%"}),
    ("委屈", {"rate": "-8%", "pitch": "-6Hz", "volume": "-3%"}),
    ("中性", {}),
)


def _emotion_row(name):
    for key, params in _EMOTION_ROWS:
        if key == name:
            return dict(params)
    return {}


def _err_text(e):
    """异常 → 人话。

    aiohttp 的 ``WSServerHandshakeError`` 用 ``str()`` 取出来是**空字符串**，
    直接拼进提示就变成"朗读失败："后面什么都没有。这里退到类型名 + HTTP 状态。
    """
    text = str(e or "").strip()
    status = getattr(e, "status", None)
    if text:
        return text[:120] + ("（HTTP %s）" % status if status else "")
    name = type(e).__name__ if e is not None else "未知错误"
    return "%s%s" % (name, "（HTTP %s）" % status if status else "")


_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# 首包到手之后，单个音频分块最多等多久（毫秒）。
# 这不是"整段总时长"：长句正常合成几十个分块也能一口气写完。
_CHUNK_TIMEOUT_MS = 12000


class _FirstPacketTimeout(Exception):
    pass


class _MidwayTimeout(Exception):
    pass


class TTS(BaseModule):

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )

    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # v2.1: 临时产物必须落在 data/plugin_data/<插件名>/ 内
        self.sandbox = data_path(self, "plugin_data", "tts")
        os.makedirs(self.sandbox, exist_ok=True)
        self.voice = _DEFAULT_VOICE
        self._count = 0
        self._last = {}

    def _voice(self):
        """当前音色：**以配置为准**（用户改了立刻生效，不用重启）。

        ``self.voice`` 只作为配置读不到时的兜底，保持旧代码的兼容。
        """
        trunk = getattr(self, "trunk", None)
        cfg = getattr(trunk, "config", None) if trunk is not None else None
        name = ""
        if isinstance(cfg, dict):
            name = str(cfg.get("tts_voice") or "").strip()
        return name or self.voice or _DEFAULT_VOICE

    # ---------------------------------------------------------- 48.3 情绪
    def _rule(self, key, default):
        try:
            return self.trunk.rule(key, default)
        except Exception as e:
            _x6_swallowed(__name__, e)
            return default

    def _mood_emotion(self):
        try:
            pers = (getattr(self.trunk, "modules", {}) or {}).get("personality")
            mood = str((getattr(pers, "data", {}) or {}).get("mood") or "中性")
        except Exception as e:
            _x6_swallowed(__name__, e)
            mood = "中性"
        return mood if any(row[0] == mood for row in _EMOTION_ROWS) else "中性"

    def emotion_params(self, emotion=None, mode=None):
        """返回 edge-tts prosody 参数；off 或中性返回空 dict（旧行为）。"""
        mode = mode or str(self._rule("语音.情绪", "on") or "off").lower()
        if mode != "on":
            return {}
        name = str(emotion or self._mood_emotion() or "中性")
        return _emotion_row(name)

    # ---------------------------------------------------------- 合成
    def _prune(self, keep=5):
        """只留最近几条音频：连聊几十轮也不会把 data 目录塞满。"""
        try:
            files = sorted(
                (os.path.join(self.sandbox, n) for n in os.listdir(self.sandbox)
                 if n.startswith("xiao6_tts_")
                 and n.endswith((".mp3", ".wav"))),
                key=os.path.getmtime)
        # 静默是故意的 - 清理失败只影响磁盘占用，不影响朗读
        except OSError as e:
            _x6_swallowed(__name__, e, "prune tts files")
            return
        for path in files[:-keep]:
            try:
                os.remove(path)
            # 静默是故意的 - 正在播放的文件删不掉，下次再清
            except OSError as e:
                _x6_swallowed(__name__, e, "remove old tts file")

    async def _speak_async(self, text, out_path, params=None, limit_ms=3000):
        """流式合成：``limit_ms`` **只约束首包**，不约束整段。

        以前 deadline 是"整段总预算"：首包 1.1~1.8 秒已经吃掉大半，
        后面的音频分块必然超时 → 每句正常回复都降级到系统朗读
        （用户看到的现象："切了音色还是同一个声音"）。
        现在首包按预算判，首包到了之后每个分块单独给 ``_CHUNK_TIMEOUT_MS``。
        """
        import edge_tts
        params = params or {}
        communicate = edge_tts.Communicate(
            text, self._voice(),
            rate=params.get("rate", "+0%"),
            pitch=params.get("pitch", "+0Hz"),
            volume=params.get("volume", "+0%"))
        started = time.time()
        loop = asyncio.get_running_loop()
        first_deadline = loop.time() + max(1, limit_ms) / 1000.0
        first_ms = None
        wrote = 0
        agen = communicate.stream()
        try:
            with open(out_path, "wb") as fp:
                while True:
                    wait = (max(0.02, first_deadline - loop.time())
                            if first_ms is None
                            else _CHUNK_TIMEOUT_MS / 1000.0)
                    try:
                        chunk = await asyncio.wait_for(agen.__anext__(), timeout=wait)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        # 首包没到手 → 按预算判定；首包到手后卡住 → 中途失败
                        if first_ms is None:
                            raise _FirstPacketTimeout() from None
                        raise _MidwayTimeout() from None
                    if chunk.get("type") == "audio" and chunk.get("data"):
                        if first_ms is None:
                            first_ms = int((time.time() - started) * 1000)
                        fp.write(chunk["data"])
                        wrote += len(chunk["data"])
        finally:
            try:
                await agen.aclose()
            except Exception as e:
                _x6_swallowed(__name__, e, "tts close")
        if not wrote:
            raise RuntimeError("没有收到音频数据")
        return first_ms or 0

    def speak(self, text: str, emotion=None, autoplay=True):
        """合成并返回 ``{"ok": True, "path": 音频绝对路径, ...}``。

        ``path`` 必须回传：``gui.workers.TTSWorker`` 靠它交给 QMediaPlayer 播放。
        这个字段以前漏了 —— worker 读到空路径，聊天里的"自动朗读"就永远静音
        （模块自己 os.startfile 又会被静音/无关联程序吞掉）。
        ``autoplay=False`` 时只合成不打开系统播放器，避免和调用方双重播放。
        """
        if not text:
            return {"ok": False, "error": "空文本"}
        # 口播清洗：去掉 **加粗** / ```代码块``` / 😊 / 链接等"只能看不能读"的东西。
        # 不洗的话会念出"星号井号"、把代码念成天书，听起来就很假。
        body = naturalize(text, 500)
        if not body:
            return {"ok": False, "error": "没有可朗读的文字"}
        mode = str(self._rule("语音.情绪", "on") or "off").lower()
        name = str(emotion or self._mood_emotion() or "中性")
        params = self.emotion_params(name, mode)
        limit = int(self._rule("语音.首包上限ms", 3000) or 3000)
        # 每次换一个文件名：同一毫秒连播两条回复也不会把正在播的文件覆盖
        self._prune()
        tmp = os.path.join(self.sandbox, "xiao6_tts_%d.mp3" % (
            int(time.time() * 1000) % 1000000))
        started = time.time()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            first_ms = loop.run_until_complete(
                self._speak_async(body, tmp, params, limit))
            loop.close()
            if autoplay:
                try:
                    os.startfile(tmp)
                except Exception as e:
                    _x6_swallowed(__name__, e, "tts open")
            self._count += 1
            self._last = {"emotion": name, "params": params,
                          "first_packet_ms": first_ms,
                          "total_ms": int((time.time() - started) * 1000)}
            return {"ok": True, "text": body[:50], "emotion": name,
                    "voice": self._voice(),
                    "first_packet_ms": first_ms, "params": params,
                    "path": tmp}
        except _FirstPacketTimeout:
            self._drop(tmp)
            return self._offline(body, name, limit, "在线语音首包超时（%d ms）" % limit,
                                 autoplay)
        except _MidwayTimeout:
            self._drop(tmp)
            return self._offline(body, name, None, "在线语音中途卡住",
                                 autoplay)
        except Exception as e:
            self._drop(tmp)
            return self._offline(body, name, 0, "在线语音失败：" + _err_text(e),
                                 autoplay)

    def _drop(self, path):
        """删掉半截音频：0 字节/断头 mp3 留着只会让下次排查误判。"""
        try:
            if path and os.path.exists(path):
                os.remove(path)
        # 静默是故意的 - 删不掉（可能正在播放）不影响兜底
        except OSError as e:
            _x6_swallowed(__name__, e, "drop partial tts file")

    # ---------------------------------------------------------- 本地兜底
    def _offline_enabled(self):
        return str(self._rule("语音.本地兜底", "on") or "on").lower() != "off"

    def _offline(self, text, name, first_ms, reason, autoplay=True):
        """在线合成失败 → 用系统朗读。

        为什么要兜底：edge-tts 依赖微软在线接口，2026-11-01 实测整站回 403，
        用户看到的就是"自动朗读开了却没声音"。系统朗读离线可用，
        音色差点，但至少有声音，不会让整个功能失效。
        """
        if not self._offline_enabled():
            return {"ok": False, "fallback": "text", "error": str(reason)[:160],
                    "first_packet_ms": first_ms, "emotion": name}
        try:
            from core.tts_fallback import speak_to_wav
            wav = os.path.join(self.sandbox, "xiao6_tts_%d.wav" % (
                int(time.time() * 1000) % 1000000))
            r = speak_to_wav(text[:500], wav, voice=self._voice())
        # 静默是故意的 - 兜底也失败，下面把两个原因一起报出去
        except Exception as e:
            _x6_swallowed(__name__, e, "offline tts")
            r = {"ok": False, "path": "", "error": _err_text(e)}
        path = str(r.get("path") or "")
        if r.get("ok") and path and os.path.exists(path):
            if autoplay:
                try:
                    os.startfile(path)
                except Exception as e:
                    _x6_swallowed(__name__, e, "tts open offline")
            self._count += 1
            self._last = {"emotion": name, "params": {}, "engine": "系统朗读",
                          "first_packet_ms": None, "total_ms": 0}
            return {"ok": True, "text": text[:50], "emotion": name,
                    "engine": "系统朗读", "fallback": "sapi", "reason": reason,
                    "first_packet_ms": first_ms, "params": {}, "path": path}
        return {"ok": False, "fallback": "text",
                "error": ("%s；本地朗读也失败：%s"
                          % (reason, r.get("error") or "未知"))[:160],
                "first_packet_ms": first_ms, "emotion": name}

    def stats(self):
        return {"总朗读次数": self._count, "声音": self._voice(),
                "最近一次": self._last}

    def run(self, text=None):
        if text:
            return self.speak(text)
        return self.stats()
