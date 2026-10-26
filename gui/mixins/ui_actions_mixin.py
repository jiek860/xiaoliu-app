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
        a_tts = menu.addAction("自动朗读开关")
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
            self._auto_tts = not getattr(self, "_auto_tts", False)
            QMessageBox.information(
                self, "自动朗读", "自动朗读已" + (
                    "开启" if self._auto_tts else "关闭"))
        elif action == a_ocr:
            self.chat.append("（截图识字功能开发中）")

    def upload_image(self):
        """发图片：选图片 → 描述图片 → 把描述加到输入框"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片文件 (*.png *.jpg *.jpeg *.gif *.bmp)")
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