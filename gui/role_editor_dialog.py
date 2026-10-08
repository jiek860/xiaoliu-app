# -*- coding: utf-8 -*-
"""自定义角色编辑器 - 群聊角色增删改"""
import os, json
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QLineEdit, QTextEdit,
    QMessageBox, QFormLayout
)
from PyQt5.QtCore import Qt


class RoleEditorDialog(QDialog):
    """自定义角色编辑器"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("自定义群聊角色")
        self.setMinimumSize(720, 560)
        self.base = getattr(trunk, "base", None) or "."
        self.path = os.path.join(self.base, "data", "custom_roles.json")
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QHBoxLayout(self)

        # 左边：角色列表
        left = QVBoxLayout()
        left.addWidget(QLabel("角色列表:"))
        self.list_w = QListWidget()
        self.list_w.currentRowChanged.connect(self._on_select)
        left.addWidget(self.list_w, stretch=1)

        row = QHBoxLayout()
        btn_add = QPushButton("新增")
        btn_add.clicked.connect(self._add)
        row.addWidget(btn_add)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete)
        row.addWidget(btn_del)
        left.addLayout(row)
        layout.addLayout(left, stretch=1)

        # 右边：编辑表单
        right = QVBoxLayout()
        form = QFormLayout()

        self.input_name = QLineEdit()
        form.addRow("名字:", self.input_name)

        self.input_avatar = QLineEdit()
        self.input_avatar.setPlaceholderText("emoji，如 👨")
        form.addRow("头像:", self.input_avatar)

        self.input_duty = QLineEdit()
        self.input_duty.setPlaceholderText("职责，如 编程技术")
        form.addRow("职责:", self.input_duty)

        self.input_keywords = QLineEdit()
        self.input_keywords.setPlaceholderText("关键词，逗号分隔，如 bug,报错,代码")
        form.addRow("关键词:", self.input_keywords)

        self.input_persona = QTextEdit()
        self.input_persona.setPlaceholderText("人设描述...")
        form.addRow("人设:", self.input_persona)

        right.addLayout(form)

        btn_save = QPushButton("保存修改")
        btn_save.setStyleSheet("background:#4a9eff;color:white;padding:8px;")
        btn_save.clicked.connect(self._save)
        right.addWidget(btn_save)

        layout.addLayout(right, stretch=1)

    def _load(self):
        if os.path.exists(self.path):
            try:
                return json.load(open(self.path, encoding="utf-8"))
            except Exception:
                pass
        return {"roles": []}

    def _save_data(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def _refresh(self):
        self.list_w.clear()
        data = self._load()
        for r in data.get("roles", []):
            item = QListWidgetItem("%s %s" % (r.get("avatar", "🧩"), r.get("name", "?")))
            item.setData(Qt.UserRole, r)
            self.list_w.addItem(item)
        if self.list_w.count() > 0:
            self.list_w.setCurrentRow(0)

    def _on_select(self, row):
        if row < 0:
            return
        item = self.list_w.item(row)
        if not item:
            return
        r = item.data(Qt.UserRole)
        self.input_name.setText(r.get("name", ""))
        self.input_avatar.setText(r.get("avatar", ""))
        self.input_duty.setText(r.get("duty", ""))
        self.input_keywords.setText(",".join(r.get("keywords", [])))
        self.input_persona.setPlainText(r.get("persona", ""))

    def _add(self):
        data = self._load()
        data.setdefault("roles", []).append({
            "name": "新角色",
            "avatar": "🧩",
            "duty": "自定义",
            "keywords": [],
            "persona": "",
        })
        self._save_data(data)
        self._refresh()
        self.list_w.setCurrentRow(self.list_w.count() - 1)

    def _delete(self):
        row = self.list_w.currentRow()
        if row < 0:
            return
        data = self._load()
        data["roles"].pop(row)
        self._save_data(data)
        self._refresh()

    def _save(self):
        row = self.list_w.currentRow()
        if row < 0:
            return
        data = self._load()
        keywords = [k.strip() for k in self.input_keywords.text().split(",") if k.strip()]
        data["roles"][row] = {
            "name": self.input_name.text().strip(),
            "avatar": self.input_avatar.text().strip() or "🧩",
            "duty": self.input_duty.text().strip(),
            "keywords": keywords,
            "persona": self.input_persona.toPlainText().strip(),
        }
        self._save_data(data)
        self._refresh()
        QMessageBox.information(self, "成功", "✅ 已保存")
