# -*- coding: utf-8 -*-
"""主窗口加号菜单、导出、截图和实时对话切换。"""
from __future__ import annotations

import os
from datetime import datetime
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QRubberBand, QFileDialog, QMessageBox, QMenu

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


# 常用中文音色（edge-tts 的 ShortName）。写在模块级不可变元组，
# 供「+ → 朗读音色」子菜单和提示文本共用，不引入网络依赖。
_TTS_VOICES = (
    ("zh-CN-XiaoxiaoNeural", "晓晓（女·温柔）"),
    ("zh-CN-XiaoyiNeural", "晓伊（女·活泼）"),
    ("zh-CN-YunxiNeural", "云希（男·少年）"),
    ("zh-CN-YunjianNeural", "云健（男·有力）"),
    ("zh-CN-YunxiaNeural", "云夏（男·稚气）"),
    ("zh-CN-YunyangNeural", "云扬（男·播报）"),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北（女·东北）"),
    ("zh-CN-shaanxi-XiaoniNeural", "晓妮（女·陕西）"),
    ("zh-HK-HiuMaanNeural", "曉曼（女·粤语）"),
    ("zh-TW-HsiaoChenNeural", "曉臻（女·台湾）"),
)


class UIActionsMixin:
    def open_web_console(self):
        """启动本地 Web 控制台并展示带 token 的访问地址。"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            srv = self.trunk.modules.get("api_server") if self.trunk else None
            if srv is None and self.trunk is not None:
                srv = self.trunk._load_lazy("api_server")
            if not srv:
                QMessageBox.warning(self, "Web 控制台", "api_server 模块未加载")
                return None
            info = srv.start()
            if not info.get("ok"):
                QMessageBox.warning(self, "Web 控制台",
                                    str(info.get("error") or "启动失败"))
                return info
            self._run_modal_once(
                "web_console",
                lambda: self._show_web_console_dialog(str(info.get("url", ""))))
            return info
        except Exception as e:
            try:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Web 控制台", "启动失败: " + str(e)[:160])
            except Exception:  # 静默是故意的：启动失败已尝试弹窗，二次提示失败不抛
                pass
            return None


    def _show_web_console_dialog(self, url):
        """用可选中、可复制的输入框展示 Web 控制台地址。"""
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from PyQt5.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                                     QLabel, QLineEdit, QVBoxLayout)

        dlg = QDialog(self)
        dlg.setWindowTitle("Web 控制台")
        dlg.setMinimumWidth(560)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("已启动。访问地址（含临时 token）："))
        edit = QLineEdit(url)
        edit.setReadOnly(True)
        edit.setCursorPosition(0)
        edit.selectAll()
        edit.setFocus()
        layout.addWidget(edit)
        tip = QLabel("token 等同于临时密码，不要发给别人。")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        buttons = QDialogButtonBox()
        copy_btn = buttons.addButton("复制链接", QDialogButtonBox.ActionRole)
        open_btn = buttons.addButton("打开浏览器", QDialogButtonBox.ActionRole)
        close_btn = buttons.addButton(QDialogButtonBox.Close)
        copy_btn.clicked.connect(
            lambda: (QApplication.clipboard().setText(edit.text()),
                     edit.selectAll()))
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(edit.text())))
        close_btn.clicked.connect(dlg.accept)
        dlg.exec_()


    def set_dialog(self):
        """设置窗口单例：未关闭时只把原窗口提到前面。"""
        cache = getattr(self, "_dialog_cache", None)
        if cache is None:
            cache = {}
            self._dialog_cache = cache
        old = cache.get("settings_dialog") or getattr(self, "_settings_dialog", None)
        if old is not None:
            try:
                if old.isVisible():
                    old.show()
                    old.raise_()
                    old.activateWindow()
                    return old
            except RuntimeError:
                self._settings_dialog = None
        from gui.settings_dialog import show_settings_dialog
        d = show_settings_dialog(
            self, self._dlg, self.trunk, self.base,
            getattr(self, "ai_name", "小6"),
            getattr(self, "model_btn", None),
            getattr(self, "_status_local", None),
            getattr(self, "_status_cloud", None),
            getattr(self, "chat", None), getattr(self, "input", None),
            self._panel_commands(),
        )
        cache["settings_dialog"] = d
        return d

    def open_skills_dialog(self):
        """打开技能管理（统一入口，供更多菜单/命令面板复用）"""
        from gui.chrome import open_panel
        return open_panel(self, "skills_dialog", "🧩 技能",
                          "gui.skills_dialog", "SkillsDialog")

    def _show_plus_menu(self):
        menu = QMenu(self)
        a_upload = menu.addAction("上传文件")
        a_image = menu.addAction("📷 发图片")
        a_editor = menu.addAction("送工作台")
        a_shot = menu.addAction("区域截图")
        a_export = menu.addAction("导出聊天记录")
        a_tts = menu.addAction("自动朗读（当前：%s）" % (
            "开" if self._auto_tts_enabled() else "关"))
        voice_menu = menu.addMenu("🔊 朗读音色（当前：%s）" % self._tts_voice_label())
        for vid, label in _TTS_VOICES:
            act = voice_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(vid == self._tts_voice())
            act.triggered.connect(
                lambda _checked=False, v=vid, lb=label: self.set_tts_voice(v, lb))
        a_preview = voice_menu.addAction("▶ 试听当前音色")
        a_ocr = menu.addAction("截图识字")
        action = menu.exec_(self.plus_btn.mapToGlobal(
            self.plus_btn.rect().bottomLeft()))
        if action == a_upload:
            self.upload_file()
        elif action == a_image:
            self.upload_image()
        elif action == a_editor:
            self.send_last_code_to_editor()
        elif action == a_shot:
            self._do_screenshot()
        elif action == a_export:
            self._do_export()
        elif action == a_tts:
            self.toggle_auto_tts()
        elif action == a_preview:
            self.preview_tts_voice()
        elif action == a_ocr:
            self.chat.append("（截图识字功能开发中）")

    # ---------------------------------------------------------- 自动朗读
    def _auto_tts_enabled(self):
        """当前是否开着自动朗读（**以配置为准**，内存属性只是缓存）。"""
        trunk = getattr(self, "trunk", None)
        cfg = getattr(trunk, "config", None) if trunk is not None else None
        if isinstance(cfg, dict):
            return bool(cfg.get("auto_tts", False))
        return bool(getattr(self, "_auto_tts", False))

    def toggle_auto_tts(self):
        """切「自动朗读」开关，并**写进 config**。

        原来的坑：这里只翻了一个内存属性 ``_auto_tts``，
        而 ``chat_mixin`` 判断的是 ``trunk.config["auto_tts"]`` ——
        菜单提示"已开启"，回复却永远不会朗读（用户以为语音坏了）。
        """
        trunk = getattr(self, "trunk", None)
        cfg = getattr(trunk, "config", None) if trunk is not None else None
        if not isinstance(cfg, dict):
            QMessageBox.warning(self, "自动朗读", "配置还没加载好，稍后再试")
            return False
        enabled = not bool(cfg.get("auto_tts", False))
        cfg["auto_tts"] = enabled
        self._auto_tts = enabled          # 兼容旧代码里读这个属性
        saved = True
        save = getattr(trunk, "save_config", None)
        if callable(save):
            try:
                save()
            # 静默是故意的 - 存盘失败也要把开关状态告诉用户，不装作成功
            except Exception as e:
                _x6_swallowed(__name__, e, "save auto_tts")
                saved = False
        tip = "自动朗读已" + ("开启" if enabled else "关闭")
        if enabled:
            tip += ("\n下一条回复会自动读出来。\n"
                    "没有声音：到「设置 → 扩展 → 功能扩展组件」检查语音合成"
                    "（edge-tts）是否装好，并确认系统音量/播放设备。")
        if not saved:
            tip += "\n（写入配置失败，重启后会恢复原样）"
        QMessageBox.information(self, "自动朗读", tip)
        return enabled

    # ---------------------------------------------------------- 朗读音色
    def _tts_voice(self):
        """当前朗读音色（**以配置为准**，与实时语音对话共用一项）。"""
        trunk = getattr(self, "trunk", None)
        cfg = getattr(trunk, "config", None) if trunk is not None else None
        if isinstance(cfg, dict):
            name = str(cfg.get("tts_voice") or "").strip()
            if name:
                return name
        return _TTS_VOICES[0][0]

    def _tts_voice_label(self):
        """给菜单显示的中文名；配置里是自己填的陌生名字就直接显示名字。"""
        cur = self._tts_voice()
        for vid, label in _TTS_VOICES:
            if vid == cur:
                return label
        return cur

    def set_tts_voice(self, voice, label=""):
        """切「朗读音色」——写进 config 并落盘，朗读和实时对话立刻生效。

        为什么写配置而不是改模块属性：朗读走插件模块 ``modules/installed/tts``、
        实时对话走 ``core/realtime``，它们各自实例化，只有共享配置才收得住。
        """
        trunk = getattr(self, "trunk", None)
        cfg = getattr(trunk, "config", None) if trunk is not None else None
        if not isinstance(cfg, dict):
            QMessageBox.warning(self, "朗读音色", "配置还没加载好，稍后再试")
            return False
        voice = str(voice or "").strip()
        if not voice:
            return False
        cfg["tts_voice"] = voice
        saved = True
        save = getattr(trunk, "save_config", None)
        if callable(save):
            try:
                save()
            # 静默是故意的 - 存盘失败也要告诉用户，不装作成功
            except Exception as e:
                _x6_swallowed(__name__, e, "save tts_voice")
                saved = False
        tip = "朗读音色已切换为：%s" % (label or voice)
        tip += ("\n「自动朗读」和「🎧 实时对话」都用这个音色，下一条就生效。\n"
                "如果在线语音连不上，程序会改用系统朗读 —— 系统里通常只有一个"
                "中文音色，只能听出音调差别（男声会自动降调）。")
        if not saved:
            tip += "\n（写入配置失败，重启后会恢复原样）"
        QMessageBox.information(self, "朗读音色", tip)
        return True

    def preview_tts_voice(self):
        """试听当前音色：念一句带标点的短句，方便判断"是不是真人感"。

        为什么要试听：音色切了到底生没生效，靠"下一条回复"验证太慢；
        直接给一句话立刻出声，还能顺带验证在线/兜底走的是哪条路。
        """
        speech = getattr(self, "speech", None)
        if speech is None or not hasattr(speech, "speak_async"):
            QMessageBox.warning(self, "试听", "语音播放还没准备好，稍后再试")
            return False
        sample = ("你好，我是%s。现在用「%s」的声音说话，"
                  "语速和停顿会尽量自然一点，你听听看。" % (
                      getattr(self, "ai_name", "") or "小6",
                      self._tts_voice_label()))
        chat = getattr(self, "chat", None)
        if chat is not None and hasattr(chat, "append"):
            chat.append("▶ 正在试听音色：%s" % self._tts_voice_label())
        try:
            on_error = getattr(self, "_tts_failed", None)
            speech.speak_async(sample, on_error=on_error if callable(on_error) else None)
        # 静默是故意的 - 试听只是辅助，失败也要回一句原因
        except Exception as e:
            _x6_swallowed(__name__, e, "preview tts voice")
            if chat is not None and hasattr(chat, "append"):
                chat.append("🔇 试听失败：%s" % str(e)[:80])
            return False
        return True

    def upload_image(self, path=None):
        """发图片：选图片（或直接用传入路径）→ 描述图片 → 描述加到输入框"""
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择图片", "",
                "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp)")
        if not path:
            return
        self.chat.append("📷 已选择图片：" + path)
        # 调 multimodal.describe_image() 描述图片
        try:
            mm = self.trunk.modules.get("multimodal") if self.trunk else None
            if mm and hasattr(mm, "describe_image"):
                self.chat.append("🔍 正在分析图片...")
                r = mm.describe_image(path)
                if isinstance(r, dict) and r.get("描述"):
                    desc = r["描述"]
                    # 把描述加到输入框（兼容 QLineEdit 和 QTextEdit）
                    if hasattr(self.input, "toPlainText"):
                        current = self.input.toPlainText()
                        self.input.setPlainText(current + " [图片描述：" + desc[:200] + "...]")
                    else:
                        current = self.input.text()
                        self.input.setText(current + " [图片描述：" + desc[:200] + "...]")
                    self.chat.append("✅ 图片分析完成，描述已加到输入框")
                else:
                    self.chat.append("❌ 图片分析失败：" + str(r)[:100])
            else:
                self.chat.append("⚠️ multimodal 模块未加载，无法分析图片")
        except Exception as e:
            self.chat.append("❌ 图片分析出错：" + str(e)[:100])

    def _do_export(self):
        from PyQt5.QtWidgets import QMessageBox
        txt = self.chat.toPlainText()
        fn = os.path.join(
            self.base,
            r"data\聊天记录_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with open(fn, "w", encoding="utf-8") as f:
            f.write(txt)
        QMessageBox.information(self, "导出", "已保存到:\n" + fn)

    def _do_screenshot(self):
        from PyQt5.QtCore import QRect, QPoint
        screen = self.screen()
        pix = screen.grabWindow(0)
        self._ss_pix = pix
        self._ss_dlg = QDialog(self)
        self._ss_dlg.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._ss_dlg.setGeometry(0, 0, screen.size().width(),
                                 screen.size().height())
        lay = QVBoxLayout(self._ss_dlg)
        lbl = QLabel()
        lbl.setPixmap(pix)
        lay.addWidget(lbl)
        self._ss_rb = QRubberBand(QRubberBand.Rectangle, lbl)

        def mousePress(e):
            self._ss_origin = e.pos()
            self._ss_rb.setGeometry(QRect(self._ss_origin, QPoint()))
            self._ss_rb.show()

        def mouseMove(e):
            self._ss_rb.setGeometry(
                QRect(self._ss_origin, e.pos()).normalized())

        def mouseRelease(e):
            rect = self._ss_rb.geometry()
            if rect.width() > 10 and rect.height() > 10:
                cropped = self._ss_pix.copy(rect)
                fn = os.path.join(
                    self.base, r"data\截图_%s.png"
                    % datetime.now().strftime("%Y%m%d_%H%M%S"))
                os.makedirs(os.path.dirname(fn), exist_ok=True)
                cropped.save(fn)
                QMessageBox.information(self, "截图", "已保存:\n" + fn)
            self._ss_dlg.close()

        lbl.mousePressEvent = mousePress
        lbl.mouseMoveEvent = mouseMove
        lbl.mouseReleaseEvent = mouseRelease
        self._ss_dlg.showFullScreen()

    def _rt_toggle(self):
        rc = self.trunk._load_lazy("realtime_chat")
        if not rc:
            return
        st = rc.status()
        if st.get("运行中"):
            rc.stop()
            self.realtime_btn.setText(" 实时对话")
        else:
            r = rc.start()
            if r.get("ok"):
                self.realtime_btn.setText(" 录音中")