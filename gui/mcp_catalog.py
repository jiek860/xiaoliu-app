# -*- coding: utf-8 -*-
"""MCP 预置服务器数据与两个展示标签页。

从 gui/mcp_dialog.py 原样搬出（该文件接近 600 行上限）。
只搬代码不改行为：数据、校验规则、界面构建逻辑与原来逐行一致。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import json

from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                             QListWidget, QListWidgetItem, QVBoxLayout,
                             QWidget)
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links


# 预置 MCP 服务器（默认值，实际从 data/mcp_catalog.json 加载）
DEFAULT_PRESETS = [
    # ===== 文件与系统 =====
    {"name": "文件系统", "cmd": "npx -y @modelcontextprotocol/server-filesystem .",
     "desc": "读写本地文件（14 个工具）", "transport": "stdio", "category": "文件系统"},
    {"name": "Git", "cmd": "uvx mcp-server-git --repository .",
     "desc": "Git 仓库操作（12 个工具）", "transport": "stdio", "category": "开发"},
    {"name": "SQLite", "cmd": 'uvx --with "mcp<2" mcp-server-sqlite --db-path data/chats.db',
     "desc": "查询 SQLite 数据库（6 个工具，已钉住 mcp SDK 1.x）", "transport": "stdio", "category": "数据库"},

    # ===== 网络与搜索 =====
    {"name": "网页抓取", "cmd": "uvx mcp-server-fetch",
     "desc": "抓取网页内容（1 个工具）", "transport": "stdio", "category": "网络"},
    {"name": "浏览器自动化", "cmd": "npx -y @modelcontextprotocol/server-puppeteer",
     "desc": "控制 Chrome 浏览器，自动化操作网页", "transport": "stdio", "category": "网络"},
    {"name": "Brave 搜索", "cmd": "npx -y @modelcontextprotocol/server-brave-search",
     "desc": "联网搜索（需要 BRAVE_API_KEY）", "transport": "stdio", "category": "网络"},

    # ===== 开发工具 =====
    {"name": "GitHub", "cmd": "npx -y @modelcontextprotocol/server-github",
     "desc": "GitHub 仓库 Issues/PR/代码搜索（需要 GITHUB_TOKEN）", "transport": "stdio", "category": "开发"},
    {"name": "PostgreSQL", "cmd": "npx -y @modelcontextprotocol/server-postgres",
     "desc": "查询 PostgreSQL 数据库", "transport": "stdio", "category": "数据库"},

    # ===== 办公与效率 =====
    {"name": "Google 日历", "cmd": "npx -y @modelcontextprotocol/server-gcal",
     "desc": "读取和管理 Google 日历事件", "transport": "stdio", "category": "办公"},
    {"name": "Google 邮箱", "cmd": "npx -y @modelcontextprotocol/server-gmail",
     "desc": "读取和发送 Gmail 邮件", "transport": "stdio", "category": "办公"},
    {"name": "Notion", "cmd": "npx -y @modelcontextprotocol/server-notion",
     "desc": "读写 Notion 页面和数据库（需要 NOTION_TOKEN）", "transport": "stdio", "category": "办公"},
    {"name": "Slack", "cmd": "npx -y @modelcontextprotocol/server-slack",
     "desc": "读取 Slack 频道消息", "transport": "stdio", "category": "办公"},

    # ===== 其他 =====
    {"name": "时间/日期", "cmd": "npx -y @modelcontextprotocol/server-time",
     "desc": "获取当前时间、时区转换", "transport": "stdio", "category": "工具"},
    {"name": "记忆", "cmd": "npx -y @modelcontextprotocol/server-memory",
     "desc": "跨会话持久记忆（知识图谱形式）", "transport": "stdio", "category": "工具"},
    {"name": "天气", "cmd": "npx -y @modelcontextprotocol/server-weather",
     "desc": "查询实时天气和预报", "transport": "stdio", "category": "工具"},
]


_ALLOWED_CMD_PREFIXES = ("npx ", "uvx ", "python ", "node ")

# JSON 配置参考（原来在 dialog_mixin.show_mcp_market）
REFERENCE = [
    ("filesystem", "文件系统访问",
     '{"mcpServers":{"filesystem":{"command":"npx",'
     '"args":["-y","@modelcontextprotocol/server-filesystem","/path/to/dir"]}}}'),
    ("fetch", "网页抓取",
     '{"mcpServers":{"fetch":{"command":"uvx","args":["mcp-server-fetch"]}}}'),
    ("git", "Git 仓库操作",
     '{"mcpServers":{"git":{"command":"uvx",'
     '"args":["mcp-server-git","--repository","/path/to/repo"]}}}'),
]


def valid_presets(items):
    """只接受结构完整、命令前缀受控的目录项，避免远程目录变成任意命令执行入口。"""
    if not isinstance(items, list) or not items or len(items) > 100:
        return False
    for p in items:
        if not isinstance(p, dict):
            return False
        if not all(str(p.get(k) or "").strip() for k in ("name", "cmd", "desc")):
            return False
        if not str(p["cmd"]).strip().lower().startswith(_ALLOWED_CMD_PREFIXES):
            return False
    return True


def load_presets():
    """从 data/mcp_catalog.json 加载预置服务器列表"""
    import os
    try:
        # 找 data 目录（相对于项目根）
        base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        catalog_path = os.path.join(base, "data", "mcp_catalog.json")
        if os.path.exists(catalog_path):
            with open(catalog_path, encoding="utf-8") as f:
                presets = json.load(f)
            if valid_presets(presets):
                return presets
    except Exception as e:
        _x6_swallowed(__name__, e, "load mcp_catalog.json failed")
    # 失败了用默认值
    return DEFAULT_PRESETS


def build_presets_tab(dialog, presets):
    """「⚡ 预置服务器」标签页。"""
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(QLabel("常用 MCP 服务器（都是 stdio 型，点「一键安装」会起子进程连上）："))
    dialog.preset_list = QListWidget()
    for p in presets:
        it = QListWidgetItem("📡 %s — %s\n      %s"
                             % (p["name"], p["desc"], p["cmd"]))
        it.setData(Qt.UserRole, p)
        dialog.preset_list.addItem(it)
    dialog.preset_list.setCurrentRow(0)
    v.addWidget(dialog.preset_list, stretch=1)

    row = QHBoxLayout()
    row.addWidget(make_action_links([
        ("复制选中命令", dialog._copy_preset_cmd),
    ]))
    install = QPushButton("⬇ 一键安装选中")
    install.setStyleSheet("background:#4a9eff;color:white;padding:8px 20px;"
                          "border:none;border-radius:6px;")
    install.clicked.connect(dialog._install_preset)
    row.addWidget(install)
    row.addStretch(1)
    v.addLayout(row)

    note = QLabel(
        "说明：这些服务器需要本机有 Node.js（npx）或 uv（uvx）。\n"
        "     首次运行时它们会去下载对应的包，可能需要等一会儿；\n"
        "     装好后就能在「🔌 服务器」页看到，并出现在已连接工具里。\n"
        "     装不上时那一页会显示失败原因（比如命令不存在、包下载失败）。"
    )
    note.setStyleSheet("color:#1e40af;background:#eff6ff;border:1px solid #bfdbfe;"
                       "border-radius:6px;padding:8px;font-size:12px;")
    note.setWordWrap(True)
    v.addWidget(note)
    return w


def build_reference_tab(dialog):
    """「📋 配置参考」标签页。"""
    w = QWidget()
    v = QVBoxLayout(w)
    v.addWidget(QLabel("各家 MCP 服务器的 JSON 配置片段（点「复制」拿走）："))
    for name, desc, cfg in REFERENCE:
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>%s</b> %s" % (name, desc)))
        row.addStretch(1)
        row.addWidget(make_action_links([
            ("复制配置", lambda _c=cfg: dialog._copy(_c)),
        ]))
        v.addLayout(row)
    v.addStretch(1)
    return w
