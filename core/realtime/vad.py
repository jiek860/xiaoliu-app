# -*- coding: utf-8 -*-
"""能量VAD：自适应噪声底"""
try:
    import numpy as np
except ImportError:
    np = None

class EnergyVAD:
    def __init__(self, sr=16000, frame_ms=30, mult=3.0, start_frames=5, end_frames=15):
        self.frame_size = int(sr * frame_ms / 1000)
        self.mult = mult
        self.start_frames = start_frames
        self.end_frames = end_frames
        self.noise_floor = 500.0
        self._v = 0
        self._s = 0
        self.state = "silence"
        self._boost = 1.0

    def boost_threshold(self, f):
        self._boost = float(f)

    def reset(self):
        self._v = 0; self._s = 0; self.state = "silence"

    def process(self, frame_bytes):
        if np is None: return "silence"
        samples = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
        if not len(samples): return "silence"
        rms = float(np.sqrt(np.mean(samples * samples)))
        if self.state == "silence":
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
        th = max(200, self.noise_floor * self.mult * self._boost)
        is_voice = rms > th
        if is_voice:
            self._v += 1; self._s = 0
        else:
            self._s += 1; self._v = 0
        if self.state == "silence" and self._v >= self.start_frames:
            self.state = "speaking"; return "start"
        if self.state == "speaking" and self._s >= self.end_frames:
            self.state = "silence"; return "end"
        return "continue" if self.state == "speaking" else "silence"

def make_vad(vad_type, **kw):
    return EnergyVAD(**kw), "energy"
