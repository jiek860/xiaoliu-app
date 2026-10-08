# -*- coding: utf-8 -*-
"""枚举麦克风设备"""
def list_input_devices():
    try: import pyaudio
    except: return []
    pa = pyaudio.PyAudio(); out = []
    try:
        default = pa.get_default_input_device_info().get("index")
    except: default = None
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) <= 0: continue
            out.append({"index": i, "name": info.get("name", ""),
                        "channels": info.get("maxInputChannels", 1),
                        "rate": int(info.get("defaultSampleRate", 16000)),
                        "default": i == default})
        except: pass
    pa.terminate()
    return out

def describe_device(idx):
    if idx < 0: return "系统默认"
    for d in list_input_devices():
        if d["index"] == idx: return d["name"]
    return "系统默认"
