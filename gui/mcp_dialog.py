# -*- coding: utf-8 -*-
"""MCP 总面板 v4.0 —— 所有跟 MCP 相关的东西都收在这一页

以前 MCP 散在四个地方：
    1. gui/mcp_dialog.py              服务器列表 / 增删测试
    2. 设置 → 扩展                     一个"MCP服务器地址"输入框 + 保存并重连
    3. dialog_mixin.show_mcp_market()  JSON 配置参考（复制到剪贴板）
    4. gui/mcp_wizard_dialog.py        一键安装向导
另外插件市场里还有个「🔌 MCP」按钮指向第 3 个。
现在统一到这里，分三个标签页：

    🔌 服务器      列表（可勾选启用/禁用）+ 测试/删除/全部重连 + 添加 + 已连接工具
    ⚡ 预置服务器   常用 MCP 服务器与它们的启动命令（可复制）
    📋 配置参考     各家服务器的 JSON 配置片段（可复制）

顺手修掉的几个老问题：
    · 列表标签一直写着"勾选启用/禁用"，但 QListWidgetItem 从来没设过 checkbox，
      勾选功能根本没实现；而 mcp_client.reload_servers() 又确实按 enabled 过滤，
      于是那个开关形同虚设。现在真的能勾。
    · _build_ui 里 `QPushButton("测试选中", clicked=...)` 建完没加进布局，
      白造一个孤儿控件；下一行才又建了一个同样的并加进去。
    · _del_selected 存完配置不调 reload_servers()，删掉的服务器客户端仍然连着。
    · _test_selected 名字叫"测试选中"，实际没看选中的是哪一行，只报了个总数。
    · 全局 config["mcp_url"] 是死设置 —— 全项目只有设置界面自己读写它，
      没有任何代码读，真正的列表是 config["mcp_servers"]。已随设置页一并移除。
    · 原「一键安装向导」把 npx/uvx 命令当 url 传给 add_server(name, url)
      （参数还多传了一个，直接 TypeError 被吞），而客户端走的是 HTTP 端点，
      两者传输方式根本不同 —— 那个按钮装什么都连不上。现在改成如实的
      "预置服务器 + 复制命令"页，不再假装能一键安装。
"""
import json

from PyQt5.QtWidgets import (QApplication, QDialog, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QListWidget, QListWidgetItem,
                             QMessageBox, QTabWidget, QWidget, QFormLayout,
                             QLineEdit)
from PyQt5.QtCore import Qt


# 预置 MCP 服务器（原来在 mcp_wizard_dialog.PRESETS）
PRESETS = [
    {"name": "文件系统", "cmd": "npx -y @modelcontextprotocol/server-filesystem .",
     "desc": "读写本地文件", "transport": "stdio"},
    {"name": "网页抓取", "cmd": "uvx mcp-server-fetch",
     "desc": "抓取网页内容", "transport": "stdio"},
    {"name": "Git", "cmd": "uvx mcp-server-git --repository .",
     "desc": "Git 仓库操作", "transport": "stdio"},
    {"name": "SQLite", "cmd": "uvx mcp-server-sqlite --db-path data/chats.db",
     "desc": "查询 SQLite 数据库", "transport": "stdio"},
]

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


class MCPDialog(QDialog):
    """MCP 总面板"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._loading = False          # 刷新列表时抑制 itemChanged 回调
        self.setWindowTitle("🔌 MCP")
        self.resize(780, 640)
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------ 界面

    def _build_ui(self):
        lay = QVBoxLayout(self)

        head = QLabel("MCP（Model Context Protocol）—— 让程序用上外部工具服务器")
        head.setStyleSheet("font-weight:bold;font-size:14px;padding:4px;")
        lay.addWidget(head)

        tabs = QTabWidget()
        tabs.addTab(self._build_servers_tab(), "🔌 服务器")
        tabs.addTab(self._build_presets_tab(), "⚡ 预置服务器")
        tabs.addTab(self._build_reference_tab(), "📋 配置参考")
        lay.addWidget(tabs, stretch=1)

        lay.addWidget(QPushButton("关闭", clicked=self.close))

    def _build_servers_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.status = QLabel("正在读取…")
        self.status.setStyleSheet("color:#475569;font-size:12px;")
        v.addWidget(self.status)

        v.addWidget(QLabel("已配置的服务器（勾选 = 启用，取消勾选 = 停用）："))
        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.addWidget(QPushButton("测试选中", clicked=self._test_selected))
        row.addWidget(QPushButton("删除选中", clicked=self._del_selected))
        row.addWidget(QPushButton("全部重连", clicked=self._reload_all))
        row.addStretch(1)
        v.addLayout(row)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：我的工具")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("HTTP 端点，例如 http://localhost:3742")
        form.addRow("名称:", self.name_edit)
        form.addRow("地址:", self.url_edit)
        form.addRow("", QPushButton("添加并连接", clicked=self._add_server))
        v.addLayout(form)

        v.addWidget(QLabel("已连接工具:"))
        self.tool_list = QListWidget()
        self.tool_list.setMaximumHeight(140)
        v.addWidget(self.tool_list)
        return w

    def _build_presets_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("常用 MCP 服务器及其启动命令（可复制到命令行手动运行）："))
        self.preset_list = QListWidget()
        for p in PRESETS:
            it = QListWidgetItem("📡 %s — %s\n      %s"
                                 % (p["name"], p["desc"], p["cmd"]))
            it.setData(Qt.UserRole, p)
            self.preset_list.addItem(it)
        self.preset_list.setCurrentRow(0)
        v.addWidget(self.preset_list, stretch=1)

        note = QLabel(
            "⚠️ 这些是 stdio 型服务器（靠命令行启动、走标准输入输出通信），\n"
            "     而当前客户端连的是 HTTP 端点（会去请求 <地址>/tools）。\n"
            "     两者传输方式不同，所以这里不提供「一键安装」—— 那种按钮装了也连不上。\n"
            "     要用它们：先在命令行跑起来，再用一个 HTTP 包装暴露 /tools，\n"
            "     然后到「🔌 服务器」页把那个地址加进来。"
        )
        note.setStyleSheet("color:#92400e;background:#fffbeb;border:1px solid #fde68a;"
                           "border-radius:6px;padding:8px;font-size:12px;")
        note.setWordWrap(True)
        v.addWidget(note)

        v.addWidget(QPushButton("复制选中命令", clicked=self._copy_preset_cmd))
        return w

    def _build_reference_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("各家 MCP 服务器的 JSON 配置片段（点按钮复制）："))
        for name, desc, cfg in REFERENCE:
            row = QHBoxLayout()
            row.addWidget(QLabel("<b>%s</b> %s" % (name, desc)))
            row.addStretch(1)
            b = QPushButton("复制配置")
            b.clicked.connect(lambda _c=False, c=cfg: self._copy(c))
            row.addWidget(b)
            v.addLayout(row)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------ 数据

    def _load_servers(self):
        return list(self.trunk.config.get("mcp_servers", []) or [])

    def _save_servers(self, servers):
        self.trunk.config["mcp_servers"] = servers
        try:
            self.trunk.save_config()
        except Exception:
            pass

    def _mcp_client(self):
        m = self.trunk.modules.get("mcp_client")
        if not m:
            try:
                m = self.trunk._load_lazy("mcp_client")
            except Exception:
                m = None
        return m

    def _sync_client(self):
        """把配置变更推给客户端。

        以前只有"添加"和"全部重连"推，删除时没推，
        于是删掉的服务器客户端还连着。
        """
        c = self._mcp_client()
        if not c:
            return None
        try:
            return c.reload_servers()
        except Exception as e:
            return {"ok": False, "错误": str(e)[:80]}

    # ------------------------------------------------------------ 刷新

    def _refresh(self):
        self._loading = True
        try:
            self.list.clear()
            servers = self._load_servers()
            for i, s in enumerate(servers):
                it = QListWidgetItem("%s  —  %s" % (s.get("name", "?"),
                                                    s.get("url", "")))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if s.get("enabled", True) else Qt.Unchecked)
                it.setData(Qt.UserRole, i)
                self.list.addItem(it)
            if servers:
                self.list.setCurrentRow(0)

            c = self._mcp_client()
            tools = list(getattr(c, "tools", []) or []) if c else []
            self.tool_list.clear()
            for t in tools[:200]:
                self.tool_list.addItem("🛠 %s" % (t.get("name") or t))
            n_on = sum(1 for s in servers if s.get("enabled", True))
            self.status.setText("共 %d 个服务器（启用 %d）· 已连接工具 %d 个"
                                % (len(servers), n_on, len(tools)))
        finally:
            self._loading = False

    # ------------------------------------------------------------ 动作

    def _on_item_changed(self, item):
        """勾选/取消勾选 -> 写回 enabled 并让客户端重连"""
        if self._loading:
            return
        i = item.data(Qt.UserRole)
        servers = self._load_servers()
        if not isinstance(i, int) or i >= len(servers):
            return
        servers[i]["enabled"] = (item.checkState() == Qt.Checked)
        self._save_servers(servers)
        self._sync_client()
        self._refresh()

    def _add_server(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "提示", "名称和地址都要填")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "地址不对",
                "地址要写成 HTTP 端点，例如 http://localhost:3742\n"
                "（stdio 型服务器需要先自己起一个 HTTP 包装，见「⚡ 预置服务器」页）")
            return
        servers = self._load_servers()
        servers.append({"name": name, "url": url, "enabled": True})
        self._save_servers(servers)
        r = self._sync_client()
        self.name_edit.clear()
        self.url_edit.clear()
        self._refresh()
        QMessageBox.information(
            self, "成功",
            "已添加 %s\n重连结果: %s"
            % (name, json.dumps(r, ensure_ascii=False) if r else "客户端未加载"))

    def _del_selected(self):
        i = self.list.currentRow()
        servers = self._load_servers()
        if i < 0 or i >= len(servers):
            QMessageBox.information(self, "提示", "请先在列表里选一个服务器")
            return
        name = servers[i].get("name", "?")
        if QMessageBox.question(self, "确认", "删除服务器「%s」？" % name,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        servers.pop(i)
        self._save_servers(servers)
        self._sync_client()            # 以前漏了这一步，删了还连着
        self._refresh()

    def _reload_all(self):
        r = self._sync_client()
        self._refresh()
        QMessageBox.information(
            self, "完成",
            "已重新连接\n" + (json.dumps(r, ensure_ascii=False) if r else "客户端未加载"))

    def _test_selected(self):
        """测试**选中的那一个**服务器（以前只报了个总数，没看选的是谁）"""
        i = self.list.currentRow()
        servers = self._load_servers()
        if i < 0 or i >= len(servers):
            QMessageBox.information(self, "提示", "请先在列表里选一个服务器")
            return
        s = servers[i]
        c = self._mcp_client()
        if not c:
            QMessageBox.warning(self, "失败", "MCP 客户端未加载")
            return
        try:
            r = c.test_server(s.get("url", ""))
        except Exception as e:
            r = {"ok": False, "错误": str(e)[:80]}
        QMessageBox.information(
            self, "测试结果",
            "服务器: %s\n地址: %s\n启用: %s\n结果: %s"
            % (s.get("name", "?"), s.get("url", ""),
               "是" if s.get("enabled", True) else "否",
               json.dumps(r, ensure_ascii=False)))

    # ------------------------------------------------------------ 复制

    def _copy(self, text):
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制", "已复制到剪贴板")

    def _copy_preset_cmd(self):
        it = self.preset_list.currentItem()
        if not it:
            QMessageBox.information(self, "提示", "请先选一个预置服务器")
            return
        self._copy(it.data(Qt.UserRole).get("cmd", ""))
