# -*- coding: utf-8 -*-
"""P0-4: 群聊角色管理对话框"""
import json, os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QTextEdit,
    QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt


class RolesDialog(QDialog):
    """群聊角色管理：列表 + 编辑 + 加删 + 导入导出"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("👥 群聊角色管理")
        self.setMinimumSize(800, 500)
        self._roles = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 按钮行
        row = QHBoxLayout()
        btn_add = QPushButton("➕ 加角色")
        btn_add.clicked.connect(self._add_role)
        row.addWidget(btn_add)
        btn_del = QPushButton("➖ 删选中")
        btn_del.clicked.connect(self._del_role)
        row.addWidget(btn_del)
        row.addStretch(1)
        btn_import = QPushButton("导入")
        btn_import.clicked.connect(self._import)
        row.addWidget(btn_import)
        btn_export = QPushButton("导出")
        btn_export.clicked.connect(self._export)
        row.addWidget(btn_export)
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_save)
        layout.addLayout(row)

        # 主体：左列表 + 右编辑
        row = QHBoxLayout()
        self.role_list = QListWidget()
        self.role_list.currentItemChanged.connect(self._on_select)
        row.addWidget(self.role_list, stretch=1)

        right = QVBoxLayout()
        right.addWidget(QLabel("角色名:"))
        self.name_input = QLineEdit()
        right.addWidget(self.name_input)
        right.addWidget(QLabel("人设 (persona):"))
        self.persona_input = QTextEdit()
        self.persona_input.setMaximumHeight(200)
        right.addWidget(self.persona_input)
        right.addWidget(QLabel("触发关键词 (逗号分隔):"))
        self.keywords_input = QLineEdit()
        right.addWidget(self.keywords_input)
        from PyQt5.QtWidgets import QWidget
        rw = QWidget()
        rw.setLayout(right)
        row.addWidget(rw, stretch=2)
        layout.addLayout(row, stretch=1)

        # 关闭
        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _load(self):
        """从 data/group_roles.json 读"""
        gc = self.trunk.modules.get("group_chat") if self.trunk else None
        if gc and hasattr(gc, "roles"):
            self._roles = gc.roles.copy()
        else:
            # 直接读文件
            path = os.path.join(getattr(self.trunk, "base", "."), "data", "group_roles.json")
            if os.path.exists(path):
                self._roles = json.load(open(path, encoding="utf-8"))
        self._render_list()

    def _render_list(self):
        self.role_list.clear()
        for name in self._roles:
            self.role_list.addItem(QListWidgetItem(name))

    def _on_select(self, current, previous):
        if not current:
            return
        name = current.text()
        role = self._roles.get(name, {})
        self.name_input.setText(name)
        self.persona_input.setPlainText(role.get("persona", ""))
        self.keywords_input.setText(", ".join(role.get("keywords", [])))

    def _add_role(self):
        name = "新角色"
        i = 1
        while name in self._roles:
            name = f"新角色{i}"
            i += 1
        self._roles[name] = {"persona": "", "keywords": []}
        self._render_list()
        # 选中新角色
        for i in range(self.role_list.count()):
            if self.role_list.item(i).text() == name:
                self.role_list.setCurrentRow(i)
                break

    def _del_role(self):
        item = self.role_list.currentItem()
        if not item:
            return
        name = item.text()
        del self._roles[name]
        self._render_list()

    def _save(self):
        """保存到 data/group_roles.json"""
        # 先把当前编辑的写回
        name = self.name_input.text().strip()
        if name:
            # 如果改名了，删掉旧的
            current_item = self.role_list.currentItem()
            if current_item and current_item.text() != name:
                old_name = current_item.text()
                if old_name in self._roles:
                    del self._roles[old_name]
            self._roles[name] = {
                "persona": self.persona_input.toPlainText().strip(),
                "keywords": [k.strip() for k in self.keywords_input.text().split(",") if k.strip()],
            }
        path = os.path.join(getattr(self.trunk, "base", "."), "data", "group_roles.json")
        json.dump(self._roles, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        QMessageBox.information(self, "保存", f"已保存 {len(self._roles)} 个角色")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入角色 JSON", "", "JSON (*.json)")
        if path:
            self._roles = json.load(open(path, encoding="utf-8"))
            self._render_list()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出角色 JSON", "group_roles.json", "JSON (*.json)")
        if path:
            json.dump(self._roles, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)