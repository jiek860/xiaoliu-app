# -*- coding: utf-8 -*-
"""TTS文字转语音模块 - 用edge-tts朗读"""
import os, asyncio, tempfile
from modules.base import BaseModule

class TTS(BaseModule):
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.voice = "zh-CN-XiaoxiaoNeural"
        self._count = 0

    async def _tts_async(self, text, out_path):
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(out_path)

    def speak(self, text: str):
        if not text:
            return {"ok": False, "error": "空文本"}
        try:
            tmp = os.path.join(tempfile.gettempdir(), "xiao6_tts.mp3")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._tts_async(text[:500], tmp))
            loop.close()
            try: os.startfile(tmp)
            except: pass
            self._count += 1
            return {"ok": True, "text": text[:50]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}

    def stats(self):
        return {"总朗读次数": self._count, "声音": self.voice}

    def run(self, text=None):
        if text: return self.speak(text)
        return self.stats()
