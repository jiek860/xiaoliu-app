# -*- coding: utf-8 -*-
"""本地语音兜底：在线合成不可用时用 Windows 系统朗读（SAPI）。

为什么需要它
-----------
``edge-tts`` 是**在线**服务。2026-11-01 实测微软接口整体回 403
（``WSServerHandshakeError: 403``），现象就是用户反馈的
"自动朗读开了，回复没有声音" —— 合成失败后没有第二条路可走。

系统朗读（System.Speech）离线可用：音色比 edge-tts 差，但**至少有声音**，
断网 / 接口被墙 / 403 时也不会让功能整体失效。

对外只有一个函数 ``speak_to_wav(text, out_path)``，返回：
    {"ok": bool, "path": 绝对路径, "error": 失败原因}
只写文件，不打开播放器 —— 播放交给调用方（QMediaPlayer / os.startfile）。
"""
from __future__ import annotations

import base64
import html
import os
import subprocess
import sys

MAX_CHARS = 800
TIMEOUT_SEC = 20
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 用 __TXT__ / __WAV__ / __SPEAK__ 占位，避免 PowerShell 的 { } 与 str.format 冲突
_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$txt = [System.IO.File]::ReadAllText('__TXT__', [System.Text.Encoding]::UTF8)
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $zh = $syn.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'zh*' } | Select-Object -First 1
  if ($zh) { $syn.SelectVoice($zh.VoiceInfo.Name) }
} catch { }
$syn.SetOutputToWaveFile('__WAV__')
__SPEAK__
$syn.Dispose()
"""

_SPEAK_PLAIN = "$syn.Speak($txt)"

# 音调版本：System.Speech 会忽略 prosody 的 voice 属性，但 pitch 真的会改波形
# （2026-11-01 实测：同一句话 pitch -6st / 0st 输出 md5 不同、长短一致）。
_SPEAK_SSML = r"""try {
  $ssml = [System.IO.File]::ReadAllText('__SSML__', [System.Text.Encoding]::UTF8)
  $syn.SpeakSsml($ssml)
} catch {
  $syn.SetOutputToWaveFile('__WAV__')
  $syn.Speak($txt)
}"""

# edge-tts 预设里的"男声"短名。离线 SAPI 通常只有一个中文音色（本机是
# Microsoft Huihui），换音色听不出来 —— 用降调做近似区分，至少能听出变化。
_MALE_MARKS = ("Yunxi", "Yunjian", "Yunxia", "Yunyang")
_MALE_PITCH = "-6st"


def available():
    """这个平台有没有系统朗读（目前只有 Windows 有）。"""
    return sys.platform.startswith("win")


def _quote(path):
    """PowerShell 单引号字符串里，单引号要写成两个。"""
    return str(path).replace("'", "''")


def _encoded(script):
    """把脚本转成 -EncodedCommand 需要的 base64（UTF-16LE）。"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _run(script, timeout):
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-EncodedCommand", _encoded(script)],
        capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _decode_error(text):
    """PowerShell 的 stderr 是 CLIXML，只挑人能读的片段。"""
    raw = str(text or "")
    if "<Objs" in raw:
        parts = []
        for chunk in raw.split('<S S="Error">')[1:]:
            parts.append(chunk.split("</S>")[0])
        raw = "".join(parts)
    raw = raw.replace("_x000D_", "").replace("_x000A_", "").replace("_x0008_", "")
    return " ".join(raw.split())[:160]


def pitch_for_voice(voice):
    """按 edge-tts 音色短名给离线朗读一个近似音调（``0st`` = 系统默认）。

    离线 SAPI 的中文音色往往只有一个，直接换音色听不出任何区别 ——
    用户就以为"切音色没生效"。男声降调处理，至少能听出变化。
    """
    name = str(voice or "")
    return _MALE_PITCH if any(m in name for m in _MALE_MARKS) else "0st"


def _ssml(text, pitch):
    """把纯文本包成 SSML（XML 转义，避免 & < > 破坏结构）。"""
    return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis'"
            " xml:lang='zh-CN'><prosody pitch='%s'>%s</prosody></speak>"
            % (pitch, html.escape(str(text), quote=False)))


def speak_to_wav(text, out_path, voice=None, timeout=TIMEOUT_SEC):
    """把 ``text`` 用系统朗读合成到 ``out_path``（wav）。

    ``voice`` 是用户选的 edge-tts 音色短名：离线没法真的换音色，
    只按性别做音调近似（见 ``pitch_for_voice``）。
    """
    body = str(text or "").strip()
    if not body:
        return {"ok": False, "path": "", "error": "空文本"}
    if not available():
        return {"ok": False, "path": "", "error": "当前系统没有可用的本地朗读（仅 Windows）"}
    out = os.path.abspath(str(out_path))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    tmp = out + ".txt"
    ssml_path = ""
    pitch = pitch_for_voice(voice)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body[:MAX_CHARS])
    # 静默是故意的 - 连临时文件都写不了，只能把原因交给调用方
    except OSError as e:
        return {"ok": False, "path": "", "error": "写临时文本失败: " + str(e)[:80]}
    if pitch != "0st":
        ssml_path = out + ".ssml"
        try:
            with open(ssml_path, "w", encoding="utf-8") as f:
                f.write(_ssml(body[:MAX_CHARS], pitch))
        # 静默是故意的 - SSML 写不出来就退回纯文本朗读
        except OSError:
            ssml_path = ""
    speak = _SPEAK_PLAIN
    if ssml_path:
        speak = (_SPEAK_SSML.replace("__SSML__", _quote(ssml_path))
                 .replace("__WAV__", _quote(out)))
    script = (_SCRIPT.replace("__TXT__", _quote(tmp))
              .replace("__WAV__", _quote(out))
              .replace("__SPEAK__", speak))
    try:
        proc = _run(script, timeout)
    # 静默是故意的 - 超时/没装 PowerShell 都归到"本地朗读不可用"
    except subprocess.TimeoutExpired:
        return {"ok": False, "path": "", "error": "本地朗读超时"}
    except OSError as e:
        return {"ok": False, "path": "", "error": "调用系统朗读失败: " + str(e)[:80]}
    finally:
        for path in (tmp, ssml_path):
            if not path:
                continue
            try:
                os.remove(path)
            # 静默是故意的 - 临时文件删不掉不影响朗读结果
            except OSError:
                pass
    if proc.returncode != 0:
        err = _decode_error(proc.stderr)
        return {"ok": False, "path": "", "error": err or "系统朗读返回失败"}
    size = os.path.getsize(out) if os.path.exists(out) else 0
    if size <= 0:
        return {"ok": False, "path": "", "error": "系统朗读没有输出音频"}
    return {"ok": True, "path": out, "error": "", "bytes": size}
