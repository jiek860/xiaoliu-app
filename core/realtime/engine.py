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


# ── 缺依赖时给用户的安装提示（统一走 core.error_text，别各写各的）──
# 为什么改：实测全项目 17 处 "pip install" 提示里**只有 1 处**带国内镜像，
# 其余都让用户直接跑 `pip install xxx` —— 那会走 PyPI 官方源，
# 国内经常慢到以为卡死。现在统一从这里出。
def _ih(pkg):
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)


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
            return {"ok": False,
                "msg": "缺少 pyaudio（语音输入要用）。\n"
                       + _ih("pyaudio pyinstaller")}
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
            # ⚠️ 整个循环体包住（2026-10-14）。原来只有 stream.read 那一步
            # 在 try 里，后面的 VAD / numpy / emit / 状态切换都裸着。
            # 其中 `self.vad.process()` 和 `self._emit()`（会调用户的
            # on_event 回调）都可能抛 —— 一抛线程就死，用户看到的是
            # "麦克风灯还亮着但没反应了"，**没有任何提示**。
            try:
                try:
                    data = self._stream.read(self.frame_size,
                                             exception_on_overflow=False)
                except Exception:
                    time.sleep(0.05)
                    continue
                if self.emit_volume:
                    self._vol_tick += 1
                    if self._vol_tick >= 3:
                        self._vol_tick = 0
                        x = np.frombuffer(data,
                                          dtype=np.int16).astype(np.float32)
                        rms = float(np.sqrt(np.mean(x*x))) if len(x) else 0
                        self._emit("volume", {"level": min(1.0, rms/4000.0),
                                              "rms": rms})
                st = self.state()
                self.vad.boost_threshold(
                    self.speak_boost if st == "SPEAKING" else 1.0)
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
            # 静默是故意的：最后一道网，只负责"别让采集线程死掉" ——
            # 它一死整个实时对话就废了，而麦克风还在采（用户以为在听）
            except Exception:
                continue

    def _asr_llm_loop(self):
        """ASR + LLM 线程

        ⚠️ 循环体**必须整体包住**（2026-10-14 修）。
        原来是这样：
            while self._running:
                try: buf = self._asr_q.get(timeout=0.3)
                except queue.Empty: continue
                self._handle_round(buf)          # ← 没包
        而 `_handle_round` 里的 try 是**从 LLM 那一段才开始的**，
        `asr.transcribe_frames()` 在 try **外面**。

        后果：ASR 抛一次异常 → 穿出 _handle_round → 穿出循环
        → **线程直接死掉**。用户看到的是"实时对话突然不应答了"，
        **没有任何报错**，界面还显示 LISTENING，只能关掉重开。

        原则：**工作线程绝不该被未处理异常杀死。**
        它跑在后台，死了没人知道，而且它是常开的（实时对话的本意）。
        """
        while self._running:
            try:
                try:
                    buf = self._asr_q.get(timeout=0.3)
                except queue.Empty:
                    continue
                self._handle_round(buf)
            # 静默是故意的：这里是**最后一道网** —— 具体错误已经由
            # _handle_round 内部各自 emit("error") 报给界面了，
            # 这一层只负责"别让线程死掉"，再报一次是重复的
            except Exception:
                continue

    def _handle_round(self, frames):
        # ⚠️ ASR 那一段也要自己兜住（2026-10-14）。
        #    原来 148 行裸着，异常会直接穿出去（见 _asr_llm_loop 的说明）。
        #    识别失败是**很常见**的事：模型文件损坏、音频格式不对、
        #    内存不够 —— 任何一种都不该让整个实时对话停摆。
        try:
            r = self.asr.transcribe_frames(frames, sr=self.sr)
        except Exception as e:
            self._emit("error", {"msg": "识别失败: %s" % str(e)[:60]})
            self._set_state("LISTENING")       # 回监听态，别卡在处理中
            return
        if not isinstance(r, dict):
            # 识别件返回了奇怪的东西（None / list）也要扛住
            self._set_state("LISTENING")
            return
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
        """TTS 线程

        ⚠️ 和 `_asr_llm_loop` 一样，循环体要**整体**包住（2026-10-14）。
        原来只有"合成"那一步在 try 里，而中间那几行不在：
            with self._rounds_lock: rr = self._rounds.get(rid)
            if self.player.current_gen() != rr["gen"]: continue
        这几行本身不容易抛，但**TTS 是走网络的**（edge-tts）——
        网络抖动、服务端改协议、代理拦截都可能让 synthesize 之外
        的环节出问题。线程一死，用户看到的是"它不回话了"，
        而且**不会有任何提示**。

        原则同 _asr_llm_loop：工作线程不该被未处理异常杀死。
        """
        while self._running:
            try:
                try:
                    rid, sent = self._tts_q.get(timeout=0.3)
                except queue.Empty:
                    continue
                with self._rounds_lock:
                    rr = self._rounds.get(rid)
                if not rr:
                    continue
                if self.player.current_gen() != rr["gen"]:
                    continue
                if sent is None:
                    self.player.end_round(rr["gen"])
                    continue
                try:
                    p = self.tts.synthesize(sent, tag=str(rid))
                    if p:
                        self.player.play(rr["gen"], p)
                except Exception as e:
                    self._emit("error", {"msg": "TTS失败: %s" % str(e)[:60]})
            # 静默是故意的：最后一道网，只负责"别让线程死掉"。
            # 具体的 TTS 错误上面已经 emit("error") 报给界面了
            except Exception:
                continue

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
        """空闲自动停止

        ⚠️ 也包住了（2026-10-14）。原来循环体一行 try 都没有：
        它虽然只做时间比较，但 `self.state()` 会拿锁、
        `self._emit()` 会调**用户回调**（`on_event`）——
        回调里抛异常（界面已经关了、控件被销毁）同样会把线程弄死。
        """
        if self.idle_stop_sec <= 0: return
        while self._running:
            try:
                time.sleep(5)
                if self.state() != "LISTENING":
                    self._last_active_t = time.time(); continue
                if time.time() - self._last_active_t >= self.idle_stop_sec:
                    self._emit("idle_timeout",
                               {"idle_sec": self.idle_stop_sec})
            # 静默是故意的：同 _asr_llm_loop —— 最后一道网，
            # 只负责别让线程死掉
            except Exception:
                continue

    def set_voice(self, v): self.tts.voice = v
    def cleanup(self): shutil.rmtree(self._tmp, ignore_errors=True)