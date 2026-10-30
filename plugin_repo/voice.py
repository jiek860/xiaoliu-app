# -*- coding: utf-8 -*-
"""语音识别模块 v2.0 - 完整版"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, time, wave, threading
from modules.base import BaseModule


def _ih(pkg):
    """缺依赖时给用户的安装提示（统一走 core.error_text，带国内源）"""
    try:
        from core.error_text import install_hint
        return install_hint(pkg)
    except Exception:
        return ("py -3 -m pip install --target optional_libs %s "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple" % pkg)

class _BackendFasterWhisper:

    # 标准 1.1：本模块不负责的事（给调用方一个明确边界，避免什么都能问）
    NOT_RESPONSIBLE = (
        "界面呈现与用户交互（由 gui 负责）",
        "模块加载、调度与权限判定（由 core 负责）",
    )
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
    except Exception as e:
        _x6_swallowed(__name__, e)
    try:
        import whisper; return "openai-whisper"
    except Exception as e:
        _x6_swallowed(__name__, e)
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
        self._stopped = False
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
            if not kind:
                raise RuntimeError("未检测到语音识别后端。\n"
                                   + _ih("faster-whisper"))
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
        while not getattr(self, "_stopped", False):
            time.sleep(60)
            if self._backend and time.time() - self._last_use >= self.idle_unload_sec:
                self.unload_model()

    def stop(self):
        """停止空闲卸载线程并立刻释放模型（模块卸载/退出时调）。

        线程本身是 daemon，进程退出会自然结束，这里用 _stopped 让它别再定时跑；
        模型对象占着内存/显存，显式置空才能立刻还回去（否则卸载后仍压着几百 MB）。
        """
        self._stopped = True
        try:
            with self._model_lock:
                self._backend = None
            self._backend_kind = None
        except Exception as e:
            _x6_swallowed(__name__, e)
        return {"ok": True, "状态": "已停止"}

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

    def listen(self, seconds=5, sample_rate=16000, stop_event=None):
        """录一段音并识别。

        ``stop_event`` 供「按住说话」用：GUI 松开按钮时 set 它，循环在每个
        1024 帧的边界检查一次，最多晚一个 buffer（约 64ms）就停，不必等满
        ``seconds``。不传就保持原来的固定时长行为。
        """
        try:
            import pyaudio
        except: return {"ok": False, "error": "缺少pyaudio"}
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, input=True, frames_per_buffer=1024)
            frames = []
            for _ in range(int(sample_rate/1024*seconds)):
                if stop_event is not None and stop_event.is_set():
                    break
                frames.append(stream.read(1024, exception_on_overflow=False))
            stream.stop_stream(); stream.close()
            sampwidth = p.get_sample_size(pyaudio.paInt16); p.terminate()
            if not frames:
                return {"ok": False, "error": "没有录到声音"}
            # v2.1: 临时产物必须落在 data/plugin_data/<插件名>/ 内（manifest 插件名为 stt）
            tmp = os.path.join(self.base, "data", "plugin_data", "stt", "_listen_tmp.wav")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(sampwidth); wf.setframerate(sample_rate)
                wf.writeframes(b"".join(frames))
            r = self.transcribe(tmp)
            try: os.remove(tmp)
            except Exception as e:
                _x6_swallowed(__name__, e)
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}

    def stats(self):
        return {"语音识别次数": self._count, "模型": "%s(%s)" % (self.model_name, self._backend_kind or "未加载"), "总识别秒": round(self._total_seconds,1)}

    def run(self, *args):
        if args and args[0]: return self.transcribe(args[0])
        return self.stats()
