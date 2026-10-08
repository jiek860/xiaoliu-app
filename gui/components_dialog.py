# -*- coding: utf-8 -*-
"""功能扩展组件窗口 - 可选功能一键安装"""
import os, sys, webbrowser
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton)


def show_components_dialog(parent, base, install_component):
    """功能扩展组件窗口"""
    d = QDialog(parent)
    d.setWindowTitle("🧩 功能扩展组件")
    d.setMinimumSize(560, 420)
    l = QVBoxLayout(d)
    intro = QLabel("以下功能默认未打包（体积大），需要时点安装，会自动下载。")
    intro.setWordWrap(True)
    l.addWidget(intro)

    comps = [
        ("语音识别（Whisper）", "faster_whisper", "faster-whisper",
         "约 500MB，首次用语音转文字时需要"),
        ("浏览器自动化", "playwright", "playwright",
         "约 80MB，装完还要在命令行跑 playwright install chromium"),
        ("语音合成 TTS", "edge_tts", "edge-tts",
         "约 10MB，让小6说话"),
    ]

    opt_dir = os.path.join(base, "optional_libs")
    os.makedirs(opt_dir, exist_ok=True)
    if opt_dir not in sys.path:
        sys.path.insert(0, opt_dir)

    for name, mod, pipname, desc in comps:
        row = QHBoxLayout()
        info = QVBoxLayout()
        title = QLabel("<b>" + name + "</b>")
        sub = QLabel(desc); sub.setStyleSheet("color:#888;font-size:11px;")
        info.addWidget(title); info.addWidget(sub)
        row.addLayout(info, 1)

        status = QLabel()
        try:
            __import__(mod); status.setText("✅ 已装")
            status.setStyleSheet("color:green;")
        except ImportError:
            status.setText("⬜ 未装")
            status.setStyleSheet("color:#888;")
        row.addWidget(status)

        btn = QPushButton("安装")
        btn.clicked.connect(lambda _, m=mod, p=pipname, st=status, b=btn:
                            install_component(m, p, st, b))
        row.addWidget(btn)
        l.addLayout(row)

    mirror_label = QLabel("安装自动走清华镜像；如仍慢，可手动选镜像：")
    mirror_label.setStyleSheet("color:#666;font-size:11px;")
    l.addWidget(mirror_label)
    mrow = QHBoxLayout()
    for label, url in [
        ("🇨🇳 清华源", "https://pypi.tuna.tsinghua.edu.cn/simple"),
        ("🇨🇳 阿里源", "https://mirrors.aliyun.com/pypi/simple"),
        ("🇨🇳 中科大源", "https://pypi.mirrors.ustc.edu.cn/simple"),
    ]:
        b = QPushButton(label)
        b.setStyleSheet("padding:4px 8px;font-size:11px;")
        b.clicked.connect(lambda _, u=url: webbrowser.open(u))
        mrow.addWidget(b)
    mrow.addStretch(1)
    l.addLayout(mrow)

    close = QPushButton("关闭"); close.clicked.connect(d.close)
    l.addWidget(close)
    d.exec_()
