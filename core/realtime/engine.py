# -*- coding: utf-8 -*-
"""实时对话主引擎 v2.1"""
import time, queue, tempfile, threading, shutil
try: import numpy as np
except: np = None
from .bus import EventBus
from .metrics import Metrics
from .vad import make_vad
from .splitter import SentenceSplitter
from .asr import ASR
from .tts import TTS
from .player import Player

class RealtimeEngine:
    def __init__(self, trunk, on_event=None, sample_rate=16000, frame_ms=30,
                 vad_mult=3.0, start_frames=5, end_frames=15,
                 tts_voice="zh-CN-XiaoxiaoNeural", speak_boost=1.5,
                 asr_model="base", device_index=-1, idle_stop_sec=0, emit_volume=True):
        self.trunk = trunk
        self.sr = sample_rate
        self.frame_size = int(sample_rate * frame_ms / 1000)
        self.speak_boost = speak_boost
        self.device_index = int(device_index)
        self.idle_stop_sec = int(idle_stop_sec)
        self.emit_volume = bool(emit_volume)
        self.bus = EventBus()
        if on_event: self.bus.subscribe("*", lambda k,d: on_event(k,d))
        self.vad, self.vad_actual = make_vad("energy", sr=sample_rate, mult=vad_mult,
                                              start_frames=start_frames, end_frames=end_frames)
        self.metrics = Metrics()
        self._tmp = tempfile.mkdtemp(prefix="xiao6_rt_")
        self.asr = ASR(self._tmp, model_name=asr_model)
        self.tts = TTS(self._tmp, voice=tts_voice)
        self.player = Player(on_start=self._on_play_start, on_end=self._on_play_end,
                             on_error=lambda m: self._emit("error", {"msg": m}))
        self._running = False
        self._state = "IDLE"
        self._state_lock = threading.Lock()
        self._rec_buf = []
        self._rec_lock = threading.Lock()
        self._asr_q = queue.Queue()
        self._tts_q = queue.Queue()
        self._rounds = {}
        self._rounds_lock = threading.Lock()
        self._pa = None
        self._stream = None
        self._vol_tick = 0
        self._last_active_t = time.time()

    def _emit(self, k, d=None): self.bus.emit(k, d or {})
    def _set_state(self, s):
        with self._state_lock:
            if self._state != s:
                self._state = s
                self._emit("state", {"state": s})
    def state(self):
        with self._state_lock: return self._state

    def start(self):
        if self._running: return {"ok": False, "msg": "已在运行"}
        if np is None: return {"ok": False, "msg": "缺少numpy"}
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
        except ImportError:
            return {"ok": False, "msg": "缺少pyaudio，请pip install pyaudio pygame"}
        self._running = True
        self.vad.reset()
        self.player.start()
        threading.Thread(target=self.asr.warmup, daemon=True).start()
        for fn in (self._capture_loop, self._asr_llm_loop, self._tts_loop, self._idle_loop):
            threading.Thread(target=fn, daemon=True).start()
        self._last_active_t = time.time()
        self._set_state("LISTENING")
        return {"ok": True, "msg": "实时对话已启动", "device": self.device_index}

    def stop(self):
        self._running = False
        self.player.stop()
        try:
            if self._stream: self._stream.stop_stream(); self._stream.close()
        except: pass
        try:
            if self._pa: self._pa.terminate()
        except: pass
        self._set_state("IDLE")
        return {"ok": True, "msg": "已停止"}

    def _capture_loop(self):
        import pyaudio
        kw = dict(format=pyaudio.paInt16, channels=1, rate=self.sr, input=True,
                  frames_per_buffer=self.frame_size)
        if self.device_index >= 0: kw["input_device_index"] = self.device_index
        try:
            self._stream = self._pa.open(**kw)
        except Exception as e:
            self._emit("error", {"msg": "打开麦克风失败: %s" % str(e)[:60]})
            self._running = False; return
        while self._running:
            try: data = self._stream.read(self.frame_size, exception_on_overflow=False)
            except: time.sleep(0.05); continue
            if self.emit_volume:
                self._vol_tick += 1
                if self._vol_tick >= 3:
                    self._vol_tick = 0
                    x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    rms = float(np.sqrt(np.mean(x*x))) if len(x) else 0
                    self._emit("volume", {"level": min(1.0, rms/4000.0), "rms": rms})
            st = self.state()
            self.vad.boost_threshold(self.speak_boost if st == "SPEAKING" else 1.0)
            ev = self.vad.process(data)
            if ev == "start":
                if st == "SPEAKING":
                    self.player.bump_gen(); self._emit("interrupted", {})
                with self._rec_lock: self._rec_buf = [data]
                self._set_state("RECORDING"); self._emit("user_start", {})
            elif ev == "continue":
                with self._rec_lock: self._rec_buf.append(data)
            elif ev == "end":
                with self._rec_lock:
                    buf = self._rec_buf; self._rec_buf = []
                if buf:
                    self._set_state("THINKING"); self._asr_q.put(buf)

    def _asr_llm_loop(self):
        while self._running:
            try: buf = self._asr_q.get(timeout=0.3)
            except queue.Empty: continue
            self._handle_round(buf)

    def _handle_round(self, frames):
        r = self.asr.transcribe_frames(frames, sr=self.sr)
        text = (r.get("text") or "").strip()
        if not text: self._set_state("LISTENING"); return
        self._last_active_t = time.time()
        self._emit("user_final", {"text": text})
        rid = int(time.time()*1000)
        gen = self.player.current_gen()
        with self._rounds_lock:
            self._rounds[rid] = {"buf": SentenceSplitter(), "gen": gen}
        try:
            def on_token(t):
                with self._rounds_lock: rr = self._rounds.get(rid)
                if not rr or self.player.current_gen() != rr["gen"]: return
                self._emit("ai_token", {"token": t})
                for s in rr["buf"].feed(t):
                    self._emit("ai_sentence", {"sentence": s})
                    self._tts_q.put((rid, s))
            ans = self.trunk.reply(text, on_token=on_token)
            with self._rounds_lock: rr = self._rounds.get(rid)
            if rr and self.player.current_gen() == rr["gen"]:
                for s in rr["buf"].flush():
                    self._emit("ai_sentence", {"sentence": s})
                    self._tts_q.put((rid, s))
            self._tts_q.put((rid, None))
            self._emit("ai_done", {"text": str(ans)[:2000]})
        except Exception as e:
            self._emit("error", {"msg": "LLM失败: %s" % str(e)[:60]})
            self._tts_q.put((rid, None))
            self._set_state("LISTENING")

    def _tts_loop(self):
        while self._running:
            try: rid, sent = self._tts_q.get(timeout=0.3)
            except queue.Empty: continue
            with self._rounds_lock: rr = self._rounds.get(rid)
            if not rr: continue
            if self.player.current_gen() != rr["gen"]: continue
            if sent is None:
                self.player.end_round(rr["gen"]); continue
            try:
                p = self.tts.synthesize(sent, tag=str(rid))
                if p: self.player.play(rr["gen"], p)
            except Exception as e:
                self._emit("error", {"msg": "TTS失败: %s" % str(e)[:60]})

    def _on_play_start(self, gen, path):
        self._set_state("SPEAKING")
        self._emit("play_start", {"path": path})
    def _on_play_end(self, gen):
        with self._rounds_lock:
            rids = [k for k,v in self._rounds.items() if v["gen"] == gen]
            for k in rids: del self._rounds[k]
        if self._running: self._set_state("LISTENING")
        self._emit("play_end", {"gen": gen})

    def _idle_loop(self):
        if self.idle_stop_sec <= 0: return
        while self._running:
            time.sleep(5)
            if self.state() != "LISTENING":
                self._last_active_t = time.time(); continue
            if time.time() - self._last_active_t >= self.idle_stop_sec:
                self._emit("idle_timeout", {"idle_sec": self.idle_stop_sec})

    def set_voice(self, v): self.tts.voice = v
    def cleanup(self): shutil.rmtree(self._tmp, ignore_errors=True)
