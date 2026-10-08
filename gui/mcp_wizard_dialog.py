# -*- coding: utf-8 -*-
"""MCP一键安装向导 - 预置服务器列表，一键安装"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QTextEdit
)
from PyQt5.QtCore import Qt


# 预置MCP服务器列表
PRESETS = [
    {
        "name": "文件系统",
        "cmd": "npx -y @modelcontextprotocol/server-filesystem",
        "desc": "读写本地文件",
        "args": ["."],
    },
    {
        "name": "网页抓取",
        "cmd": "uvx mcp-server-fetch",
        "desc": "抓取网页内容",
        "args": [],
    },
    {
        "name": "Git",
        "cmd": "uvx mcp-server-git",
        "desc": "Git仓库操作",
        "args": ["--repository", "."],
    },
    {
        "name": "SQLite",
        "cmd": "uvx mcp-server-sqlite",
        "desc": "查询SQLite数据库",
        "args": ["--db-path", "data/chats.db"],
    },
]


class MCPWizardDialog(QDialog):
    """MCP一键安装向导"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("MCP 一键安装向导")
        self.setMinimumSize(640, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("🔌 MCP 服务器一键安装")
        title.setStyleSheet("font-size:16px;font-weight:bold;padding:6px;")
        layout.addWidget(title)

        tip = QLabel("选择一个MCP服务器，自动配置到程序里。")
        tip.setStyleSheet("color:#666;padding:4px;")
        layout.addWidget(tip)

        # 预置列表
        layout.addWidget(QLabel("预置服务器:"))
        self.list_w = QListWidget()
        for p in PRESETS:
            item = QListWidgetItem("📡 %s - %s" % (p["name"], p["desc"]))
            item.setData(Qt.UserRole, p)
            self.list_w.addItem(item)
        layout.addWidget(self.list_w, stretch=1)

        # 按钮
        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        btn_install = QPushButton("安装选中")
        btn_install.setStyleSheet("background:#4a9eff;color:white;padding:8px 20px;")
        btn_install.clicked.connect(self._install)
        row.addWidget(btn_install)
        layout.addLayout(row)

    def _install(self):
        item = self.list_w.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择一个服务器")
            return
        preset = item.data(Qt.UserRole)

        # 调用mcp_client添加服务器
        try:
            mc = self.trunk.modules.get("mcp_client")
            if not mc:
                # 尝试加载
                mc = self.trunk._load_lazy("mcp_client")
            if mc and hasattr(mc, "add_server"):
                r = mc.add_server(preset["name"], preset["cmd"], preset.get("args", []))
                if r.get("成功") or r.get("ok"):
                    QMessageBox.information(self, "成功", "✅ 已安装: " + preset["name"])
                    self.accept()
                    return
                else:
                    QMessageBox.warning(self, "失败", "安装失败: " + str(r.get("error", "")))
            else:
                QMessageBox.information(self, "提示", "mcp_client 未加载，请手动配置")
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e)[:100])
