# -*- coding: utf-8 -*-
"""新手教程窗口 - 激活/模型安装/聊天引导"""
import webbrowser
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QPlainTextEdit)


def show_tutorial_dialog(parent):
    """新手教程窗口"""
    d = QDialog(parent)
    d.setWindowTitle("📖 新手教程")
    d.setMinimumSize(640, 680)
    l = QVBoxLayout(d)
    txt = QPlainTextEdit(); txt.setReadOnly(True)
    txt.setPlainText(
        "小6智能助手 · 快速上手\n\n"
        "【第一步：激活账号】\n"
        "  1. 启动后弹出登录框 → 点「激活」\n"
        "  2. 输入自己起的账号名 + 激活码 → 激活\n"
        "  3. 回到登录框，输入账号名 → 登录\n"
        "  ※ 一个激活码只能激活一个账号\n\n"
        "【第二步：配模型】\n"
        "  · 本地模型：需要先装 Ollama（见下方导航）\n"
        "  · 云端模型：设置里填 OpenAI 兼容 API 地址和 Key\n\n"
        "═══════ 本地模型（Ollama）安装导航 ═══════\n\n"
        "1) 点下方按钮下载 OllamaSetup.exe（任选一个能打开的地址）\n"
        "2) 双击安装，一路下一步，默认会加 PATH\n"
        "3) 装完开始菜单出现小羊驼图标，后台自动启动\n"
        "4) 按 Win+R 输入 cmd，打开命令行，执行：\n"
        "       ollama run qwen2.5:3b\n"
        "   （第一次会下载模型，约 2GB，等它跑完）\n"
        "5) 回到小6：设置 → 检测本地模型 → 选 qwen2.5:3b\n\n"
        "⚠ 如果模型下载慢：右键开始菜单 → PowerShell，执行：\n"
        "       setx OLLAMA_MODEL_SERVER \"https://mirror.ollama.com\"\n"
        "   然后重启 Ollama 再拉模型。\n\n"
        "【第三步：聊天】\n"
        "  直接在底部输入框说话，回车发送。\n"
        "  AI 给的代码，点输入框旁边 📥 按钮送进编辑器。\n\n"
        "【代码编辑器】\n"
        "  顶部 📝编辑器 按钮打开：多标签、运行、AI修复、文件树。\n\n"
        "【出问题】\n"
        "  日志中心左下角「📦 导出日志包」一键打包发开发者。"
    )
    l.addWidget(txt)

    row1 = QHBoxLayout()
    row1.addWidget(QLabel("Ollama 下载："))
    for label, url in [
        ("🌐 官网", "https://ollama.com/download/windows"),
        ("🐙 GitHub", "https://github.com/ollama/ollama/releases/latest"),
        ("⚡ 加速镜像", "https://ghproxy.net/https://github.com/ollama/ollama/releases/latest"),
    ]:
        b = QPushButton(label)
        b.setStyleSheet("padding:4px 10px;")
        b.clicked.connect(lambda _, u=url: webbrowser.open(u))
        row1.addWidget(b)
    l.addLayout(row1)

    row2 = QHBoxLayout()
    row2.addWidget(QLabel("模型："))
    for label, url in [
        ("📦 Qwen2.5", "https://ollama.com/library/qwen2.5:4b"),
        ("📦 DeepSeek-R1", "https://ollama.com/library/deepseek-r1:7b"),
        ("🇨🇳 魔搭社区", "https://modelscope.cn/models?name=qwen2.5"),
        ("🇨🇳 HF镜像", "https://hf-mirror.com/models?search=qwen2.5"),
    ]:
        b = QPushButton(label)
        b.setStyleSheet("padding:4px 10px;")
        b.clicked.connect(lambda _, u=url: webbrowser.open(u))
        row2.addWidget(b)
    l.addLayout(row2)

    btn = QPushButton("知道了"); btn.clicked.connect(d.close)
    l.addWidget(btn)
    d.exec_()
