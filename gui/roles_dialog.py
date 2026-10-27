# -*- coding: utf-8 -*-
"""P0-4: 群聊角色管理对话框

控件预算：整窗只留「保存」一个按钮，加/删/导入/导出都改成链接。
另外补齐三处会直接抛异常的地方：
    · 导入一份坏 JSON -> 现在给原因，不再弹 traceback
    · 导出到不可写目录 -> 现在提示换目录
    · 保存后没有同步给已加载的 group_chat 模块 -> 群聊里还是旧人设
"""
import json
import os

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QWidget, QMessageBox, QFileDialog,
)

from gui.feedback_states import make_action_links


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

    def _path(self):
        return os.path.join(getattr(self.trunk, "base", ".") or ".",
                            "data", "group_roles.json")

    def _build_ui(self):
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(make_action_links([
            ("➕ 加角色", self._add_role),
            ("➖ 删选中", self._del_role),
            ("📥 导入", self._import),
            ("📤 导出", self._export),
        ]))
        row.addStretch(1)
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
        rw = QWidget()
        rw.setLayout(right)
        row.addWidget(rw, stretch=2)
        layout.addLayout(row, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("Esc 关闭"))
        layout.addLayout(row)

    def _load(self):
        gc = self.trunk.modules.get("group_chat") if self.trunk else None
        if gc and hasattr(gc, "roles"):
            self._roles = gc.roles.copy()
        elif os.path.exists(self._path()):
            try:
                with open(self._path(), encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._roles = data
            except Exception as e:
                QMessageBox.warning(
                    self, "读取角色失败",
                    "data/group_roles.json 解析不了：%s\n先显示空列表，"
                    "修好文件或重新导入一份。" % str(e)[:120])
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
        for i in range(self.role_list.count()):
            if self.role_list.item(i).text() == name:
                self.role_list.setCurrentRow(i)
                break

    def _del_role(self):
        item = self.role_list.currentItem()
        if not item:
            QMessageBox.information(self, "删除角色", "先在左边列表里选中一个角色")
            return
        name = item.text()
        if QMessageBox.question(
                self, "删除角色", "确定删除「%s」？保存后才真正生效。" % name,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        self._roles.pop(name, None)
        self._render_list()

    def _save(self):
        name = self.name_input.text().strip()
        if name:
            current_item = self.role_list.currentItem()
            if current_item and current_item.text() != name:
                old_name = current_item.text()
                if old_name in self._roles:
                    del self._roles[old_name]
            self._roles[name] = {
                "persona": self.persona_input.toPlainText().strip(),
                "keywords": [k.strip() for k in
                             self.keywords_input.text().split(",") if k.strip()],
            }
        try:
            os.makedirs(os.path.dirname(self._path()), exist_ok=True)
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(self._roles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(
                self, "保存失败",
                "写不进 %s：%s\n检查目录权限后重试。" % (self._path(), str(e)[:120]))
            return
        # 已加载的群聊模块要跟着换，否则保存完聊天里还是旧人设
        gc = self.trunk.modules.get("group_chat") if self.trunk else None
        if gc is not None and hasattr(gc, "roles"):
            gc.roles = dict(self._roles)
        self._render_list()
        QMessageBox.information(self, "保存", "已保存 %d 个角色" % len(self._roles))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入角色 JSON", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层必须是 {角色名: {...}} 的对象")
        except Exception as e:
            QMessageBox.warning(self, "导入失败",
                                "这个文件读不出来：%s" % str(e)[:150])
            return
        self._roles = data
        self._render_list()
        QMessageBox.information(
            self, "导入完成", "读入 %d 个角色，点「保存」才会写进配置" % len(data))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出角色 JSON", "group_roles.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._roles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "导出失败",
                                "写不进这个位置：%s\n换个目录再试。" % str(e)[:120])
            return
        QMessageBox.information(self, "导出完成", "已导出 %d 个角色" % len(self._roles))
