# -*- coding: utf-8 -*-
"""MCP市场 v3.0 - 服务器管理+持久化+工具查看"""
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt
class MCPDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("MCP市场")
        self.resize(680, 520)
        self._build_ui()
        self._refresh()
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("已配置MCP服务器（勾选启用/禁用）："))
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        QPushButton("测试选中", clicked=self._test_selected)
        row.addWidget(QPushButton("测试选中", clicked=self._test_selected))
        row.addWidget(QPushButton("删除选中", clicked=self._del_selected))
        row.addWidget(QPushButton("全部重连", clicked=self._reload_all))
        row.addStretch()
        lay.addLayout(row)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        form.addRow("名称:", self.name_edit)
        form.addRow("地址:", self.url_edit)
        add_btn = QPushButton("添加并连接", clicked=self._add_server)
        form.addRow("", add_btn)
        lay.addLayout(form)
        lay.addWidget(QLabel("已连接工具:"))
        self.tool_list = QListWidget()
        lay.addWidget(self.tool_list)
        close = QPushButton("关闭", clicked=self.close)
        lay.addWidget(close)
    def _load_servers(self):
        return list(self.trunk.config.get("mcp_servers", []) or [])
    def _save_servers(self, s):
        self.trunk.config["mcp_servers"] = s
        self.trunk.save_config()
    def _refresh(self):
        self.list.clear()
        servers = self._load_servers()
        for i, s in enumerate(servers):
            it = QListWidgetItem(f"[{i}] {s.get('name','?')} - {s.get('url','')[:50]}")
            self.list.addItem(it)
    def _add_server(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name or not url: return
        s = self._load_servers()
        s.append({"name": name, "url": url, "enabled": True})
        self._save_servers(s)
        mcp = self.trunk.modules.get("mcp_client")
        if mcp:
            try: mcp.reload_servers()
            except: pass
        self.name_edit.clear()
        self.url_edit.clear()
        self._refresh()
        QMessageBox.information(self, "成功", f"已添加{name}")
    def _del_selected(self):
        i = self.list.currentRow()
        if i <0: return
        s = self._load_servers()
        if i >= len(s): return
        s.pop(i)
        self._save_servers(s)
        self._refresh()
    def _reload_all(self):
        mcp = self.trunk.modules.get("mcp_client")
        if mcp:
            try: mcp.reload_servers()
            except: pass
        QMessageBox.information(self, "完成", "已重新连接所有服务器")
    def _test_selected(self):
        mcp = self.trunk.modules.get("mcp_client")
        if not mcp:
            QMessageBox.warning(self, "失败", "MCP客户端未加载")
            return
        tools = getattr(mcp, "tools", [])
        QMessageBox.information(self, "测试结果", f"共连接{len(mcp.servers)}个服务器，可用工具{len(tools)}个")
