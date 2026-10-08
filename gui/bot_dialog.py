# -*- coding: utf-8 -*-
"""机器人对话框 v2.0 - 企业微信 + 钉钉完整版"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QComboBox, QMessageBox,
                             QTabWidget, QTextEdit, QGroupBox)
from PyQt5.QtCore import QEvent, QTimer
from core.bot_server import BotServer


class BotDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        if not hasattr(trunk, "bot_server") or trunk.bot_server is None:
            trunk.bot_server = BotServer(trunk)
        self.bot = trunk.bot_server
        self.setWindowTitle("机器人")
        self.setFixedSize(450, 420)
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 状态
        self.status = QLabel("状态: 未启动")
        self.status.setStyleSheet("font-weight:bold;")
        layout.addWidget(self.status)

        # 企业微信
        wecom_group = QGroupBox("企业微信")
        wecom_layout = QVBoxLayout(wecom_group)
        wecom_layout.addWidget(QLabel("Webhook 地址:"))
        self.wecom_webhook = QLineEdit()
        self.wecom_webhook.setPlaceholderText("粘贴企业微信群机器人地址")
        wecom_layout.addWidget(self.wecom_webhook)
        layout.addWidget(wecom_group)

        # 钉钉
        dingtalk_group = QGroupBox("钉钉")
        dingtalk_layout = QVBoxLayout(dingtalk_group)
        dingtalk_layout.addWidget(QLabel("Webhook 地址:"))
        self.dingtalk_webhook = QLineEdit()
        self.dingtalk_webhook.setPlaceholderText("粘贴钉钉群机器人地址")
        dingtalk_layout.addWidget(self.dingtalk_webhook)
        layout.addWidget(dingtalk_group)

        # 日志
        log_group = QGroupBox("消息日志")
        log_layout = QVBoxLayout(log_group)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        log_layout.addWidget(self.log)
        layout.addWidget(log_group)

        # 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("启动")
        self.start_btn.setStyleSheet("background:#4a9eff;color:white;border:none;padding:6px 20px;border-radius:4px;")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)

        self.test_btn = QPushButton("发测试消息")
        self.test_btn.clicked.connect(self._test)
        btn_row.addWidget(self.test_btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _start(self):
        # 配置webhook
        wecom = self.wecom_webhook.text().strip()
        dingtalk = self.dingtalk_webhook.text().strip()
        if not wecom and not dingtalk:
            QMessageBox.warning(self, "提示", "请至少填一个Webhook地址")
            return

        if wecom:
            self.bot.set_wecom_webhook(wecom)
            self.trunk.config["wecom_webhook"] = wecom
            self.trunk.save_config()
        if dingtalk:
            self.bot.set_dingtalk_webhook(dingtalk)
            self.trunk.config["dingtalk_webhook"] = dingtalk
            self.trunk.save_config()

        # 启动服务器
        r = self.bot.start(9000)
        if r.get("成功"):
            self.status.setText(f"状态: ● 已启动，端口 {r.get('端口')}")
            self.status.setStyleSheet("color:green;font-weight:bold;")
            self.log.append("✅ 机器人服务已启动")
            self.log.append(f"   企业微信回调地址: http://你的IP:9000/wecom")
            self.log.append(f"   钉钉回调地址: http://你的IP:9000/dingtalk")
            self.start_btn.setEnabled(False)
        else:
            QMessageBox.critical(self, "错误", f"启动失败: {r.get('错误')}")

    def _test(self):
        wecom = self.wecom_webhook.text().strip()
        dingtalk = self.dingtalk_webhook.text().strip()
        if wecom:
            self.bot.set_wecom_webhook(wecom)
            self.trunk.config["wecom_webhook"] = wecom
            self.trunk.save_config()
            if self.bot.send_wecom("✅ 测试消息：小6机器人已连接成功！"):
                self.log.append("📨 已发测试消息到企业微信")
        if dingtalk:
            self.bot.set_dingtalk_webhook(dingtalk)
            self.trunk.config["dingtalk_webhook"] = dingtalk
            self.trunk.save_config()
            if self.bot.send_dingtalk("✅ 测试消息：小6机器人已连接成功！"):
                self.log.append("📨 已发测试消息到钉钉")

    def _load_config(self):
        """加载配置"""
        cfg = self.trunk.config
        if cfg.get("wecom_webhook"):
            self.wecom_webhook.setText(cfg["wecom_webhook"])
        if cfg.get("dingtalk_webhook"):
            self.dingtalk_webhook.setText(cfg["dingtalk_webhook"])
        # 读取机器人状态
        if self.bot.running:
            self.status.setText(f"状态: ● 已启动，端口 {self.bot.port}")
            self.status.setStyleSheet("color:green;font-weight:bold;")
            self.start_btn.setEnabled(False)

    def event(self, e):
        if e.type() == QEvent.EnterWhatsThisMode:
            QMessageBox.information(self, "使用方法",
                "1. 在企业微信/钉钉群里\n"
                "   群设置 → 群机器人 → 添加机器人\n"
                "2. 复制 Webhook 地址\n"
                "3. 粘贴到上面，点启动\n"
                "4. 在群里发消息试试\n\n"
                "注意：回调地址需要外网能访问\n"
                "（可以用内网穿透工具）")
            return True
        return super().event(e)

    def closeEvent(self, e):
        # 不stop bot_server，让它后台运行
        super().closeEvent(e)
