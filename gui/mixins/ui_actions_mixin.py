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
    def _show_plus_menu(self):
        menu = QMenu(self)
        a_upload = menu.addAction("上传文件")
        a_editor = menu.addAction("送代码编辑器")
        a_shot = menu.addAction("区域截图")
        a_export = menu.addAction("导出聊天记录")
        a_tts = menu.addAction("自动朗读开关")
        a_ocr = menu.addAction("截图识字")
        action = menu.exec_(self.plus_btn.mapToGlobal(
            self.plus_btn.rect().bottomLeft()))
        if action == a_upload:
            self.upload_file()
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
