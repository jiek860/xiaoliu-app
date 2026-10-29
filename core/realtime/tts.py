# -*- coding: utf-8 -*-
"""TTS：edge-tts封装（48.3 起支持按情绪调语速/音调）"""
import os, asyncio, time

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
    def __init__(self, tmp_dir, voice="zh-CN-XiaoxiaoNeural"):
        self.tmp_dir = tmp_dir
        self.voice = voice
        self._stop = False

    def available(self):
        try:
            import edge_tts; return {"edge_tts": True, "pyttsx3": False}
        except ImportError:
            return {"edge_tts": False, "pyttsx3": False}

    def stop(self):
        self._stop = True

    def synthesize(self, text, tag="", emotion=None):
        if not text.strip(): return None
        import edge_tts
        out = os.path.join(self.tmp_dir, "tts_%s_%d.mp3" % (tag, int(time.time()*1000)%100000))
        rate, pitch, volume = _EMOTION_PARAMS.get(str(emotion or ""),
                                                ("+0%", "+0Hz", "+0%"))
        com = edge_tts.Communicate(text, self.voice, rate=rate,
                                  pitch=pitch, volume=volume)
        asyncio.run(com.save(out))
        return out if os.path.exists(out) else None

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
        except: return []
