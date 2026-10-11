# -*- coding: utf-8 -*-
"""语音识别模块 v2.0 - 完整版"""
import os, time, wave, threading
from modules.base import BaseModule

class _BackendFasterWhisper:
    name = "faster-whisper"
    def __init__(self, model_name="base", device="cpu", compute_type="int8"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        self.model_name = model_name
    def transcribe(self, audio, **kw):
        segs, info = self.model.transcribe(audio, **kw)
        segments = [{"start": float(s.start), "end": float(s.end), "text": s.text} for s in segs]
        text = "".join(s["text"] for s in segments).strip()
        return {"text": text, "segments": segments, "language": getattr(info, "language", None), "duration": float(getattr(info, "duration", 0) or 0)}

class _BackendOpenAIWhisper:
    name = "openai-whisper"
    def __init__(self, model_name="base", device="cpu", compute_type="int8"):
        import whisper
        self.model = whisper.load_model(model_name, device=device)
        self.model_name = model_name
    def transcribe(self, audio, **kw):
        kw.pop("vad_filter", None); kw.pop("beam_size", None)
        result = self.model.transcribe(audio, **kw)
        segments = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]} for s in result.get("segments", [])]
        return {"text": result.get("text", "").strip(), "segments": segments, "language": result.get("language"), "duration": segments[-1]["end"] if segments else 0}

def _detect_backend():
    try:
        import faster_whisper; return "faster-whisper"
    except: pass
    try:
        import whisper; return "openai-whisper"
    except: pass
    return None

class Voice(BaseModule):
    def __init__(self, trunk=None):
        super().__init__(trunk)
        self.base = getattr(trunk, "base", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg = getattr(trunk, "config", {}) or {}
        self.model_name = cfg.get("asr_model", "base")
        self.device = cfg.get("asr_device", "auto")
        self.compute_type = cfg.get("asr_compute_type", "int8")
        self.language = cfg.get("asr_language", "zh")
        self.vad_filter = bool(cfg.get("asr_vad_filter", True))
        self.beam_size = int(cfg.get("asr_beam_size", 5))
        self.idle_unload_sec = int(cfg.get("asr_idle_unload_sec", 1800))
        self._backend = None
        self._backend_kind = None
        self._model_lock = threading.Lock()
        self._last_use = 0.0
        self._count = 0
        self._total_seconds = 0.0
        self._total_chars = 0
        self._hotwords = []
        threading.Thread(target=self._idle_unload_loop, daemon=True).start()

    def _pick_device(self):
        if self.device and self.device != "auto": return self.device
        try:
            import torch; return "cuda" if torch.cuda.is_available() else "cpu"
        except: return "cpu"

    def _load_backend(self):
        if self._backend is not None: return self._backend
        with self._model_lock:
            if self._backend is not None: return self._backend
            kind = _detect_backend()
            if not kind: raise RuntimeError("未检测到whisper后端，请pip install faster-whisper")
            device = self._pick_device()
            if kind == "faster-whisper":
                self._backend = _BackendFasterWhisper(self.model_name, device=device, compute_type=self.compute_type)
            else:
                self._backend = _BackendOpenAIWhisper(self.model_name, device=device)
            self._backend_kind = kind
            return self._backend

    def unload_model(self):
        with self._model_lock: self._backend = None
        return {"ok": True}

    def _idle_unload_loop(self):
        if self.idle_unload_sec <= 0: return
        while True:
            time.sleep(60)
            if self._backend and time.time() - self._last_use >= self.idle_unload_sec:
                self.unload_model()

    def transcribe(self, audio_path, language=None, hotwords=None, **kw):
        if not isinstance(audio_path, str): return {"ok": False, "error": "不支持数组输入"}
        if not os.path.exists(audio_path): return {"ok": False, "error": "音频文件不存在"}
        try:
            backend = self._load_backend()
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}
        kw = {}
        if self.language != "auto": kw["language"] = self.language
        if self._backend_kind == "faster-whisper":
            kw["vad_filter"] = self.vad_filter; kw["beam_size"] = self.beam_size
        t0 = time.time()
        try:
            result = backend.transcribe(audio_path, **kw)
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}
        dt = time.time() - t0
        text = result.get("text", "")
        self._count += 1; self._total_seconds += dt; self._total_chars += len(text)
        self._last_use = time.time()
        return {"ok": True, "text": text}

    def listen(self, seconds=5, sample_rate=16000):
        try:
            import pyaudio
        except: return {"ok": False, "error": "缺少pyaudio"}
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, input=True, frames_per_buffer=1024)
            frames = []
            for _ in range(int(sample_rate/1024*seconds)):
                frames.append(stream.read(1024, exception_on_overflow=False))
            stream.stop_stream(); stream.close()
            sampwidth = p.get_sample_size(pyaudio.paInt16); p.terminate()
            tmp = os.path.join(self.base, "data", "_listen_tmp.wav")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(sampwidth); wf.setframerate(sample_rate)
                wf.writeframes(b"".join(frames))
            r = self.transcribe(tmp)
            try: os.remove(tmp)
            except: pass
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}

    def stats(self):
        return {"语音识别次数": self._count, "模型": "%s(%s)" % (self.model_name, self._backend_kind or "未加载"), "总识别秒": round(self._total_seconds,1)}

    def run(self, *args):
        if args and args[0]: return self.transcribe(args[0])
        return self.stats()
