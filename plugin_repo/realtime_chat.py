# -*- coding: utf-8 -*-
"""实时对话模块 v2.1"""
import os, time
from modules.base import BaseModule

class RealtimeChat(BaseModule):
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.engine = None
        self.event_log = []
        self.stats = {"轮数": 0, "打断": 0, "错误": 0}

    def _on_event(self, kind, data):
        self.event_log.append({"t": time.time(), "kind": kind, "data": data})
        if len(self.event_log) > 500: self.event_log = self.event_log[-200:]
        if kind == "user_final": self.stats["轮数"] += 1
        elif kind == "interrupted": self.stats["打断"] += 1
        elif kind == "error": self.stats["错误"] += 1

    def start(self, voice=None, device=-1):
        if self.engine and self.engine._running:
            return {"ok": False, "msg": "已在运行"}
        from core.realtime import RealtimeEngine
        self.engine = RealtimeEngine(self.trunk, on_event=self._on_event,
                                      tts_voice=voice or "zh-CN-XiaoxiaoNeural",
                                      device_index=device)
        return self.engine.start()

    def stop(self):
        if not self.engine: return {"ok": False, "msg": "未启动"}
        return self.engine.stop()

    def status(self):
        running = bool(self.engine and self.engine._running)
        st = self.engine.state() if self.engine else "IDLE"
        return {"运行中": running, "状态": st, "统计": self.stats}

    def list_devices(self):
        from core.realtime.audio_devices import list_input_devices
        return {"devices": list_input_devices()}

    def list_voices(self):
        from core.realtime.tts import TTS
        t = TTS(os.path.join(self.base, "data"))
        return {"voices": t.list_voices()}

    def run(self, *args):
        if args:
            cmd = str(args[0]).lower()
            if cmd == "start": return self.start()
            if cmd == "stop": return self.stop()
            if cmd == "devices": return self.list_devices()
            if cmd == "voices": return self.list_voices()
        return self.status()
