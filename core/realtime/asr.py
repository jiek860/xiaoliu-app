# -*- coding: utf-8 -*-
"""ASR：faster-whisper封装"""
import os, wave, threading

class ASR:
    def __init__(self, tmp_dir, model_name="base"):
        self.tmp_dir = tmp_dir
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def available(self):
        try:
            import faster_whisper; return True
        except ImportError:
            return False

    def warmup(self):
        self.transcribe_frames([], sr=16000)

    def transcribe_frames(self, frames, sr=16000):
        if not frames: return {"text": ""}
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            wav = os.path.join(self.tmp_dir, "asr_in.wav")
            with wave.open(wav, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
                wf.writeframes(b"".join(frames))
            segs, _ = self._model.transcribe(wav, language="zh")
            text = "".join(s.text for s in segs).strip()
            return {"text": text}
