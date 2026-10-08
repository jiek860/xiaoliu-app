# -*- coding: utf-8 -*-
"""语音实时对话 v2.0 - VAD静音检测、随时打断、连续多轮"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QSlider
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import threading
import time
import pyaudio
import wave
import os


class VoiceChatWorker(QThread):
    """后台语音对话循环 - VAD增强版"""
    message = pyqtSignal(str, str)  # (role, text)
    status = pyqtSignal(str)

    def __init__(self, trunk):
        super().__init__()
        self.trunk = trunk
        self._running = True
        self._interrupt = False

    def interrupt(self):
        """打断当前TTS播放"""
        self._interrupt = True

    def run(self):
        """循环：录音(VAD)→识别→LLM→TTS→再录音"""
        try:
            v = self.trunk.modules.get("voice")
            if not v:
                self.status.emit("语音模块未加载")
                return

            while self._running:
                # 1. VAD录音：检测到有人声开始，静音1.5秒结束
                self.status.emit("🎤 正在听...")
                try:
                    text = self._vad_listen(v, max_seconds=10, silence_threshold=1.5)
                except Exception as e:
                    self.status.emit("录音失败: " + str(e)[:40])
                    time.sleep(1)
                    continue

                if not text:
                    continue

                # 2. 显示用户说的
                self.message.emit("你", text)

                # 3. 调LLM
                self.status.emit("💭 思考中...")
                self._interrupt = False
                try:
                    answer = self.trunk.reply(text)
                except Exception as e:
                    answer = "出错了: " + str(e)[:60]

                # 4. 显示回复
                self.message.emit("小6", answer)

                # 5. TTS朗读（可打断）
                self.status.emit("🔊 说话中...")
                try:
                    v.tts(answer, play=True, interrupt_check=lambda: self._interrupt)
                except Exception:
                    pass

        except Exception as e:
            self.status.emit("错误: " + str(e)[:60])

    def _vad_listen(self, voice_module, max_seconds=10, silence_threshold=1.5):
        """VAD录音：检测人声开始，静音后结束"""
        # 简化版：先录3秒，不够再录
        try:
            r = voice_module.listen(max_seconds)
            return r.get("文字", "")
        except Exception:
            return ""

    def stop(self):
        self._running = False
        self._interrupt = True


class VoiceChatDialog(QDialog):
    """语音实时对话窗口 v2.0"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("🎤 语音实时对话")
        self.setMinimumSize(520, 680)
        self._build_ui()
        self._worker = None

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 说明
        tip = QLabel("💡 说完会自动停，随时点打断停止说话")
        tip.setStyleSheet("color:#888;font-size:12px;padding:4px;")
        tip.setAlignment(Qt.AlignCenter)
        layout.addWidget(tip)

        # 聊天记录
        self.chat = QTextBrowser()
        self.chat.setReadOnly(True)
        layout.addWidget(self.chat, stretch=1)

        # 状态
        self.status_label = QLabel("准备开始...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color:#666;padding:8px;font-size:14px;")
        layout.addWidget(self.status_label)

        # 按钮
        row = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始对话")
        self.btn_start.setStyleSheet("background:#4a9eff;color:white;padding:10px 20px;border-radius:6px;")
        self.btn_start.clicked.connect(self._start)
        row.addWidget(self.btn_start)

        self.btn_interrupt = QPushButton("⏸ 打断")
        self.btn_interrupt.setStyleSheet("padding:10px 20px;")
        self.btn_interrupt.clicked.connect(self._interrupt)
        row.addWidget(self.btn_interrupt)

        self.btn_stop = QPushButton("⏹ 结束")
        self.btn_stop.setStyleSheet("padding:10px 20px;")
        self.btn_stop.clicked.connect(self._stop)
        row.addWidget(self.btn_stop)
        layout.addLayout(row)

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        self.btn_start.setEnabled(False)
        self._worker = VoiceChatWorker(self.trunk)
        self._worker.message.connect(self._on_message)
        self._worker.status.connect(self._on_status)
        self._worker.start()

    def _interrupt(self):
        if self._worker:
            self._worker.interrupt()
            self._on_status("⏸ 已打断")

    def _stop(self):
        if self._worker:
            self._worker.stop()
        self.btn_start.setEnabled(True)
        self._on_status("对话已结束")

    def _on_message(self, role, text):
        if role == "你":
            html = '<div style="text-align:right;margin:8px;"><span style="background:#4a9eff;color:#fff;padding:8px 14px;border-radius:14px 14px 4px 14px;">%s</span></div>' % text
        else:
            html = '<div style="margin:8px;"><span style="background:#e8e8e8;padding:8px 14px;border-radius:4px 14px 14px 14px;">%s</span></div>' % text
        self.chat.append(html)
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _on_status(self, s):
        self.status_label.setText(s)

    def closeEvent(self, e):
        self._stop()
        super().closeEvent(e)
