# -*- coding: utf-8 -*-
"""按住说话：短按走 5 秒，长按松开即停，松开后的 click 被吞掉。"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import pytest

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit  # noqa: E402

from gui.mixins.voice_mixin import VoiceMixin  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Btn:
    def __init__(self):
        self.text = "语音输入"
        self.enabled = True

    def setText(self, text):
        self.text = text

    def setEnabled(self, on):
        self.enabled = bool(on)


class _Speech:
    def __init__(self):
        self.calls = []

    def listen_once(self, seconds=5, stop_event=None):
        self.calls.append((seconds, stop_event))
        return {"文字": "你好", "错误": ""}


class _Win(VoiceMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.voice_btn = _Btn()
        self.input = QTextEdit()
        self.speech = _Speech()
        self.dialogs = []


def _pump(timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def test_short_press_falls_back_to_five_seconds():
    w = _Win()
    w._voice_pressed()
    w._voice_released()
    assert w._voice_stop is None
    w._voice_btn_clicked()
    assert w.speech.calls and w.speech.calls[0][0] == 5
    _pump()
    assert "你好" in w.input.toPlainText()
    assert w.voice_btn.text == "语音输入"


def test_long_press_stops_and_suppresses_click():
    w = _Win()
    w._voice_pressed()
    w._begin_held_recording()
    assert w._voice_recording is True
    assert w.speech.calls[-1][0] == VoiceMixin.HOLD_MAX_SECONDS
    w._voice_released()
    assert w._voice_stop is not None and w._voice_stop.is_set()
    w._voice_btn_clicked()      # 松开后 Qt 会补一个 click：应被吞掉
    assert len(w.speech.calls) == 1
    _pump()
    assert "你好" in w.input.toPlainText()


def test_begin_hold_without_event_is_noop():
    w = _Win()
    w._begin_held_recording()
    assert getattr(w, "_voice_recording", False) is False
    assert w.speech.calls == []


def test_pressed_while_recording_is_ignored():
    w = _Win()
    w._voice_recording = True
    w._voice_pressed()
    assert w.speech.calls == []


def test_partial_preview_then_final_replaces_it():
    """流式中间结果只做预览；最终结果以最后识别为准，不重复追加。"""
    w = _Win()
    w.input.setPlainText("前缀")
    w._voice_recording = True
    w._voice_base_text = "前缀"
    w._on_voice_partial("你好")
    assert w.input.toPlainText() == "前缀 你好"
    w._on_voice_done("你好世界", "")
    assert w.input.toPlainText() == "前缀 你好世界"
    assert w._voice_base_text is None
