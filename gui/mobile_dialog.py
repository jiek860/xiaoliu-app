# -*- coding: utf-8 -*-
"""手机远程对话框 - 可视化管理手机连接"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QLineEdit, QMessageBox)


class MobileDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("手机远程")
        self.setFixedSize(450, 350)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("手机远程控制")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # 状态
        self.status_label = QLabel("状态: 未连接")
        layout.addWidget(self.status_label)

        # 发送消息
        layout.addWidget(QLabel("发消息到手机:"))
        self.msg_edit = QLineEdit()
        self.msg_edit.setPlaceholderText("输入消息内容")
        layout.addWidget(self.msg_edit)

        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self._send_msg)
        layout.addWidget(send_btn)

        # 底部
        btn_row = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _send_msg(self):
        """发消息到手机"""
        msg = self.msg_edit.text().strip()
        if not msg:
            QMessageBox.warning(self, "提示", "请输入消息")
            return
        try:
            mr = self.trunk.modules.get("mobile_remote")
            if not mr:
                self.trunk._load_lazy("mobile_remote")
                mr = self.trunk.modules.get("mobile_remote")
            if mr and hasattr(mr, "send"):
                r = mr.send("小6通知", msg)
                QMessageBox.information(self, "成功", "已发送")
            else:
                QMessageBox.warning(self, "提示", "手机远程模块未就绪")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e)[:80])
