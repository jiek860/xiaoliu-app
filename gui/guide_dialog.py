# -*- coding: utf-8 -*-
"""新手引导对话框 - 第一次用弹引导"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QTextBrowser)
from PyQt5.QtCore import Qt


class GuideDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("新手引导")
        self.setFixedSize(500, 450)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("👋 欢迎使用小6智能助手")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        text = QTextBrowser()
        text.setHtml("""
        <h3>快速开始</h3>
        <ol>
        <li><b>激活</b>：点登录窗口的"激活"按钮，输入激活码</li>
        <li><b>聊天</b>：底部输入框打字，按 Enter 发送</li>
        <li><b>功能中心</b>：左侧边栏，里面有设置/插件/日志</li>
        </ol>
        <h3>小6会什么</h3>
        <ul>
        <li>💬 聊天：闲聊/问答/写代码</li>
        <li>🔍 联网：问天气/新闻</li>
        <li>🧠 记忆：记住你说过的话</li>
        <li>💻 电脑：帮你打开软件</li>
        </ul>
        <h3>需要模型吗</h3>
        <p>小6用 Ollama 跑本地模型。如果没装 Ollama，小6会提示你。</p>
        """)
        layout.addWidget(text)

        btn = QPushButton("开始使用")
        btn.clicked.connect(self.close)
        layout.addWidget(btn)
