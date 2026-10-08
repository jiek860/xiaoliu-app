# -*- coding: utf-8 -*-
"""反馈对话框 - 右上角反馈按钮"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QMessageBox)
import smtplib
from email.mime.text import MIMEText


class FeedbackDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("意见反馈")
        self.setFixedSize(450, 320)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("💬 意见反馈")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(QLabel("遇到什么问题？有什么建议？"))
        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("请输入反馈内容...")
        layout.addWidget(self.content_edit)

        btn_row = QHBoxLayout()
        submit_btn = QPushButton("提交")
        submit_btn.setStyleSheet("background-color: #2196f3; color: white; border: none; padding: 8px 20px; border-radius: 6px;")
        submit_btn.clicked.connect(self._submit)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(submit_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _submit(self):
        """发送反馈到邮箱（从config读配置）"""
        content = self.content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, "提示", "请输入反馈内容")
            return
        try:
            # 从config读邮箱配置，不硬编码
            cfg = self.trunk.config if hasattr(self.trunk, 'config') else {}
            smtp_to = cfg.get("feedback_email_to", "")
            smtp_user = cfg.get("feedback_email_user", "")
            smtp_pass = cfg.get("feedback_email_pass", "")
            smtp_server = cfg.get("feedback_smtp_server", "smtp.qq.com")
            smtp_port = int(cfg.get("feedback_smtp_port", "465"))

            if not smtp_to or not smtp_user or not smtp_pass:
                QMessageBox.warning(self, "提示", "反馈邮箱未配置，请联系开发者")
                return

            msg = MIMEText("反馈内容:\n%s" % content)
            msg["Subject"] = "小6反馈"
            msg["From"] = smtp_user
            msg["To"] = smtp_to
            s = smtplib.SMTP_SSL(smtp_server, smtp_port)
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, smtp_to, msg.as_string())
            s.quit()
            QMessageBox.information(self, "成功", "感谢反馈！")
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "错误", "发送失败: " + str(e)[:60])
