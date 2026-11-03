# -*- coding: utf-8 -*-
"""枚举麦克风设备"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

def list_input_devices():
    try: import pyaudio
    except Exception: return []
    pa = pyaudio.PyAudio(); out = []
    try:
        default = pa.get_default_input_device_info().get("index")
    except Exception: default = None
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) <= 0: continue
            out.append({"index": i, "name": info.get("name", ""),
                        "channels": info.get("maxInputChannels", 1),
                        "rate": int(info.get("defaultSampleRate", 16000)),
                        "default": i == default})
        except Exception as e:
            _x6_swallowed(__name__, e)
    pa.terminate()
    return out
