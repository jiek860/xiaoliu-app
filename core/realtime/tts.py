# -*- coding: utf-8 -*-
"""TTS：edge-tts封装（48.3 起支持按情绪调语速/音调）

2026-11-01：在线接口整体回 403（``WSServerHandshakeError``）时，
退回 ``core.tts_fallback`` 的系统朗读（离线），避免语音对话整体静音。
"""
import os, asyncio, time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

try:
    from core.tts_text import naturalize
except ImportError:  # 老安装里没有 core.tts_text：退化成只截长度
    def naturalize(text, limit=500):
        return str(text or "").strip()[:limit]

_DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

_EMOTION_PARAMS = {
    "开心": ("+8%", "+10Hz", "+5%"),
    "活泼": ("+5%", "+6Hz", "+0%"),
    "精神": ("+3%", "+4Hz", "+0%"),
    "轻松": ("+0%", "+2Hz", "+0%"),
    "慵懒": ("-8%", "-4Hz", "-5%"),
    "低落": ("-10%", "-8Hz", "-5%"),
    "委屈": ("-8%", "-6Hz", "-3%"),
}


class TTS:
    def __init__(self, tmp_dir, voice=None):
        self.tmp_dir = tmp_dir
        # 音色：调用方没指定就用默认（实时对话那边会传 config["tts_voice"]）
        self.voice = str(voice or _DEFAULT_VOICE)
        self._stop = False

    def available(self):
        try:
            import edge_tts; return {"edge_tts": True, "pyttsx3": False}
        except ImportError:
            return {"edge_tts": False, "pyttsx3": False}

    def stop(self):
        self._stop = True

    def synthesize(self, text, tag="", emotion=None):
        # 口播清洗：实时对话的句子也会带 emoji/符号，洗过之后更像人说话
        body = naturalize(text, 300)
        if not body:
            return None
        out = os.path.join(self.tmp_dir, "tts_%s_%d.mp3" % (tag, int(time.time()*1000)%100000))
        rate, pitch, volume = _EMOTION_PARAMS.get(str(emotion or ""),
                                                ("+0%", "+0Hz", "+0%"))
        try:
            import edge_tts
            com = edge_tts.Communicate(body, self.voice, rate=rate,
                                      pitch=pitch, volume=volume)
            asyncio.run(com.save(out))
            if os.path.exists(out) and os.path.getsize(out) > 0:
                return out
        # 静默是故意的 - 在线合成失败退回本地朗读，不能让语音对话整体静音
        except Exception as e:
            _x6_swallowed(__name__, e, "edge tts synthesize")
        return self._offline(body, out[:-4] + ".wav")

    def _offline(self, text, out_path):
        """系统朗读兜底：微软接口 403 / 断网时至少还有声音。

        音色也一起传过去：离线只有系统音色，靠音调近似区分男女声。
        """
        try:
            from core.tts_fallback import speak_to_wav
            r = speak_to_wav(text[:500], out_path, voice=self.voice)
        # 静默是故意的 - 兜底也失败就返回 None，调用方只显示文字
        except Exception as e:
            _x6_swallowed(__name__, e, "offline tts synthesize")
            return None
        path = str(r.get("path") or "")
        return path if r.get("ok") and path and os.path.exists(path) else None

    def list_voices(self, only_chinese=True):
        import asyncio, edge_tts
        async def _ls():
            vs = await edge_tts.list_voices()
            out = []
            for v in vs:
                loc = v.get("Locale", "")
                if only_chinese and not loc.startswith("zh-"): continue
                out.append({"id": v.get("ShortName"), "name": v.get("FriendlyName"),
                            "gender": v.get("Gender"), "locale": loc})
            return out
        try: return asyncio.run(_ls())
        except Exception: return []
