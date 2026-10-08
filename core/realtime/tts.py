# -*- coding: utf-8 -*-
"""TTS：edge-tts封装"""
import os, asyncio, time, threading

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

    def synthesize(self, text, tag=""):
        if not text.strip(): return None
        import edge_tts
        out = os.path.join(self.tmp_dir, "tts_%s_%d.mp3" % (tag, int(time.time()*1000)%100000))
        com = edge_tts.Communicate(text, self.voice)
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
