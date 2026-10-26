# -*- coding: utf-8 -*-
"""语音实时对话 v2.1 - 录音→识别→回复→朗读→再录音（可随时打断）

这一轮修掉的四个真问题
----------------------
1. 朗读调的是 `voice_module.tts(...)` —— Voice 模块根本没有 tts 方法，
   异常被吞掉，于是"语音对话"从头到尾只有文字、没有声音。
2. 打断只置了一个标志，没有任何播放器接收 —— 点了「打断」也停不下来。
3. 识别失败时把错误丢掉、`continue` 重录 —— 麦克风坏掉时界面一直显示
   "正在听..." 空转，用户不知道发生了什么。
4. 回复走的是 `trunk.reply(text)` 默认路径：长句会被"复杂任务"判定接走，
   在后台同步等最多 45 秒，语音对话像卡死。现在固定 `force_chat=True`。

现在的分工：worker 只做录音/识别/调模型，**不碰控件**；朗读交给 GUI 线程
（`_VoiceSynth` 生成音频 → QMediaPlayer 播放），播放结束通过 threading.Event
通知 worker 继续听 —— 避免喇叭声音被麦克风录回去。
"""
import html
import os
import threading
import time

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser
from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal

from gui.feedback_states import make_action_links


class _VoiceSynth(QThread):
    """后台合成朗读音频，只发路径回 GUI 线程。

    为什么不用 gui.workers.TTSWorker：那个走的是插件市场的 `tts` 模块，
    它的 speak() 直接 os.startfile 打开系统播放器 —— 停不下来，也没法打断。
    这里用 core.realtime.tts 只生成文件，播放交给 QMediaPlayer，才能真打断。
    """
    done = pyqtSignal(str)

    def __init__(self, trunk, text):
        super().__init__()
        self.trunk = trunk
        self.text = str(text or "")

    def run(self):
        path = ""
        try:
            from core.realtime.tts import TTS
            base = getattr(self.trunk, "base", "") or os.getcwd()
            tmp = os.path.join(base, "data", "plugin_data", "voice_chat")
            os.makedirs(tmp, exist_ok=True)
            path = TTS(tmp).synthesize(self.text[:500], tag="voice") or ""
        except Exception as e:  # 静默是故意的 - 合成失败只降级成文字
            _x6_swallowed(__name__, e, "voice tts synth")
            path = ""
        try:
            self.done.emit(path)
        except Exception as e:  # 静默是故意的 - 窗口已关闭
            _x6_swallowed(__name__, e, "voice tts signal")


class VoiceChatWorker(QThread):
    """后台语音对话循环 - 录音(VAD)→识别→LLM→(GUI 朗读)→再录音"""
    message = pyqtSignal(str, str)  # (role, text)
    status = pyqtSignal(str)
    speak = pyqtSignal(str)         # 交给 GUI 线程去朗读
    failed = pyqtSignal(str)        # 致命错误（模块缺失 / 连续录音失败）

    MAX_ERRORS = 3

    def __init__(self, trunk):
        super().__init__()
        self.trunk = trunk
        self._running = True
        self._interrupt = False
        self._errors = 0
        # 朗读结束（或被打断）后置位；worker 等它，避免自己听自己
        self.speech_done = threading.Event()

    def interrupt(self):
        """打断当前TTS播放：停止播放并让循环立刻继续"""
        self._interrupt = True
        self.speech_done.set()

    def run(self):
        """循环：录音→识别→LLM→TTS→再录音"""
        try:
            v = self.trunk.modules.get("voice") or self.trunk._load_lazy("voice")
            if not v:
                self.status.emit("语音模块没加载起来")
                self.failed.emit(
                    "到「设置 → 扩展 → 功能扩展组件」装上「语音识别」后再试")
                return

            while self._running:
                # 1. VAD录音：检测到有人声开始，静音1.5秒结束
                self.status.emit("🎤 正在听...")
                try:
                    text, err = self._vad_listen(v, max_seconds=10)
                except Exception as e:
                    text, err = "", "录音失败: " + str(e)[:60]

                if not self._running:
                    break
                if err:
                    self._errors += 1
                    self.status.emit("录音失败: " + err[:60])
                    if self._errors >= self.MAX_ERRORS:
                        self.failed.emit("连续 %d 次录音失败，先停下来：%s"
                                         % (self._errors, err[:80]))
                        return
                    time.sleep(0.5)
                    continue
                self._errors = 0
                if not text:
                    continue

                # 2. 显示用户说的
                self.message.emit("你", text)

                # 3. 调LLM —— force_chat=True：语音对话不该被"复杂任务"接走等 45 秒
                self.status.emit("💭 思考中...")
                self._interrupt = False
                try:
                    answer = self.trunk.reply(text, force_chat=True)
                except Exception as e:
                    answer = "出错了: " + str(e)[:60]
                if not self._running:
                    break

                # 4. 显示回复
                self.message.emit("小6", answer)

                # 5. 朗读（GUI 线程播，结束/打断后放行；最多等 45 秒）
                self.status.emit("🔊 说话中...")
                self.speech_done.clear()
                self.speak.emit(answer)
                self.speech_done.wait(45)
                if not self._running:
                    break

            self.status.emit("对话已结束")
        except Exception as e:
            self.status.emit("错误: " + str(e)[:60])

    def _vad_listen(self, voice_module, max_seconds=10):
        """录一次音，返回 (文字, 错误)。

        Voice.listen() 返回的是 {ok, text, error}；以前这里读的是
        `r.get("文字")`，键名对不上，识别成功也返回空 → 循环永远不说话。
        """
        r = voice_module.listen(max_seconds)
        if not isinstance(r, dict):
            return "", "语音模块返回格式不对"
        if r.get("ok") is False:
            return "", str(r.get("error") or "识别失败")[:100]
        text = str(r.get("text") or r.get("文字") or "").strip()
        return text, "" if text else "没听清，再说一遍试试"

    def stop(self):
        self._running = False
        self._interrupt = True
        self.speech_done.set()


class VoiceChatDialog(QDialog):
    """语音实时对话窗口 v2.1"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("🎤 语音实时对话")
        self.setMinimumSize(520, 680)
        self._worker = None
        self._synth = None
        self._player = None
        self._speech_end = None
        self._build_ui()

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

        # 打断 / 结束都是随时可点的辅助动作 → 链接（按钮预算只许降）
        row.addWidget(make_action_links([
            ("⏸ 打断", self._interrupt),
            ("⏹ 结束", self._stop),
        ]))
        row.addStretch(1)
        layout.addLayout(row)

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        self.btn_start.setEnabled(False)
        self._on_status("🎤 正在听...")
        self._worker = VoiceChatWorker(self.trunk)
        self._worker.message.connect(self._on_message)
        self._worker.status.connect(self._on_status)
        self._worker.speak.connect(self._speak)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _interrupt(self):
        if self._player is not None:
            try:
                self._player.stop()
            except Exception as e:  # 静默是故意的 - 停播失败不影响打断
                _x6_swallowed(__name__, e, "voice player stop")
        if self._worker:
            self._worker.interrupt()
        self._on_status("⏸ 已打断")

    def _stop(self):
        if self._synth is not None and self._synth.isRunning():
            self._synth.wait(1000)
        if self._player is not None:
            try:
                self._player.stop()
            except Exception as e:  # 静默是故意的 - 关闭窗口时的收尾
                _x6_swallowed(__name__, e, "voice player stop")
        if self._worker:
            self._worker.stop()
            if self._worker.isRunning():
                self._worker.wait(2000)
        self.btn_start.setEnabled(True)
        self._on_status("对话已结束")

    def _on_message(self, role, text):
        safe = html.escape(str(text or ""))
        if role == "你":
            bubble = ('<div style="text-align:right;margin:8px;">'
                      '<span style="background:#4a9eff;color:#fff;padding:8px 14px;'
                      'border-radius:14px 14px 4px 14px;">%s</span></div>' % safe)
        else:
            bubble = ('<div style="margin:8px;">'
                      '<span style="background:#e8e8e8;padding:8px 14px;'
                      'border-radius:4px 14px 14px 14px;">%s</span></div>' % safe)
        self.chat.append(bubble)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_status(self, s):
        self.status_label.setText(s)

    def _on_failed(self, err):
        """worker 自己停了（模块缺失 / 连续录音失败）——说清原因并放行按钮"""
        self.status_label.setText("⚠ " + str(err)[:160])

    def _on_worker_finished(self):
        self.btn_start.setEnabled(True)
        if self.status_label.text().startswith("🎤"):
            self.status_label.setText("对话已结束")

    def _speak(self, text):
        """在 GUI 线程里朗读：后台合成音频 → QMediaPlayer 播放"""
        self._release_speech()          # 上一段还没结束的话先放行
        self._synth = _VoiceSynth(self.trunk, text)
        self._synth.done.connect(self._on_tts_ready)
        self._synth.start()

    def _on_tts_ready(self, path):
        if not path:
            # 没装 edge-tts / 合成失败：不朗读，但必须放行 worker，否则它一直等
            self._on_status("（没装语音合成 edge-tts，先只显示文字）")
            self._release_speech()
            return
        try:
            from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
        except Exception as e:  # 静默是故意的 - 没有 QtMultimedia 就只显示文字
            _x6_swallowed(__name__, e, "voice multimedia unavailable")
            self._on_status("（当前环境不能播放音频，只显示文字）")
            self._release_speech()
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._player.mediaStatusChanged.connect(self._on_media_status)
        self._speech_end = {QMediaPlayer.EndOfMedia, QMediaPlayer.InvalidMedia,
                            QMediaPlayer.NoMedia}
        self._player.stop()
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._player.play()

    def _on_media_status(self, status):
        if self._speech_end and status in self._speech_end:
            self._release_speech()

    def _release_speech(self):
        if self._worker is not None:
            self._worker.speech_done.set()

    def closeEvent(self, e):
        self._stop()
        super().closeEvent(e)
