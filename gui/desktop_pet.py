# -*- coding: utf-8 -*-
"""P1-17: 桌面悬浮窗"""
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QPoint


class DesktopPet(QWidget):
    """桌面悬浮小6"""
    def __init__(self, trunk=None, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = QPoint()
        self._build_ui()
        self.resize(100, 100)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        label = QLabel("🤖")
        label.setStyleSheet("font-size:64px;")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)

    def mouseDoubleClickEvent(self, e):
        """双击弹出主窗口"""
        if self.trunk:
            try:
                win = self.trunk.main_window
                if win:
                    win.showNormal()
                    win.activateWindow()
            except Exception:
                pass
