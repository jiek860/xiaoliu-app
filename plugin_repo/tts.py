# -*- coding: utf-8 -*-
"""TTS文字转语音模块 - 用edge-tts朗读（批次 48.3 加心境情绪与首包预算）

情绪不是玄学：按当前 mood 调 edge-tts 的 rate / pitch / volume，语气更贴
"开心/低落/慵懒"。``语音.情绪`` off 时完全回到旧行为（只传文本和音色）。

首包预算：``语音.首包上限ms`` 默认 1500。流式合成第一块音频超过预算就
取消并返回 ``{"ok": False, "fallback": "text"}``；调用方应直接显示文本，
不要让用户干等。合成成功时返回 ``first_packet_ms``，供 49.2 性能观察。
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


class _FirstPacketTimeout(Exception):
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
        self.sandbox = os.path.join(self.base, "data", "plugin_data", "tts")
        os.makedirs(self.sandbox, exist_ok=True)
        self.voice = "zh-CN-XiaoxiaoNeural"
        self._count = 0
        self._last = {}

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
    async def _speak_async(self, text, out_path, params=None, limit_ms=1500):
        import edge_tts
        params = params or {}
        communicate = edge_tts.Communicate(
            text, self.voice,
            rate=params.get("rate", "+0%"),
            pitch=params.get("pitch", "+0Hz"),
            volume=params.get("volume", "+0%"))
        started = time.time()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1, limit_ms) / 1000.0
        first_ms = None
        wrote = 0
        agen = communicate.stream()
        try:
            with open(out_path, "wb") as fp:
                while True:
                    remain = deadline - loop.time()
                    if remain <= 0:
                        raise _FirstPacketTimeout()
                    try:
                        chunk = await asyncio.wait_for(agen.__anext__(), timeout=remain)
                    except StopAsyncIteration:
                        break
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

    def speak(self, text: str, emotion=None):
        if not text:
            return {"ok": False, "error": "空文本"}
        mode = str(self._rule("语音.情绪", "on") or "off").lower()
        name = str(emotion or self._mood_emotion() or "中性")
        params = self.emotion_params(name, mode)
        limit = int(self._rule("语音.首包上限ms", 1500) or 1500)
        tmp = os.path.join(self.sandbox, "xiao6_tts.mp3")
        started = time.time()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            first_ms = loop.run_until_complete(
                self._speak_async(text[:500], tmp, params, limit))
            loop.close()
            try:
                os.startfile(tmp)
            except Exception as e:
                _x6_swallowed(__name__, e, "tts open")
            self._count += 1
            self._last = {"emotion": name, "params": params,
                          "first_packet_ms": first_ms,
                          "total_ms": int((time.time() - started) * 1000)}
            return {"ok": True, "text": text[:50], "emotion": name,
                    "first_packet_ms": first_ms, "params": params}
        except _FirstPacketTimeout:
            return {"ok": False, "fallback": "text", "error": "语音首包超时",
                    "first_packet_ms": limit, "emotion": name}
        except Exception as e:
            return {"ok": False, "fallback": "text", "error": str(e)[:80],
                    "emotion": name}

    def stats(self):
        return {"总朗读次数": self._count, "声音": self.voice,
                "最近一次": self._last}

    def run(self, text=None):
        if text:
            return self.speak(text)
        return self.stats()
