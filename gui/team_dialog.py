# -*- coding: utf-8 -*-
"""团队管理窗口：用户、角色、集中配置、审计导出。"""
from __future__ import annotations

import json

from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout,
)

from core.team_policy import ROLES, TeamStore
from gui.feedback_states import make_action_links


class TeamDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.base = getattr(trunk, "base", "") or "."
        self.store = TeamStore(self.base)
        self.setWindowTitle("团队 / 多用户管理")
        self.resize(760, 650)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("用户与角色（owner/admin/editor/viewer/auditor）:"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["用户 ID", "名称", "角色", "状态"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)

        add = QHBoxLayout()
        self.uid = QLineEdit()
        self.uid.setPlaceholderText("用户 ID")
        self.uname = QLineEdit()
        self.uname.setPlaceholderText("显示名称")
        self.role = QComboBox()
        self.role.addItems(list(ROLES))
        add_btn = make_action_links([("➕ 添加用户", self._add_user)])
        add.addWidget(self.uid)
        add.addWidget(self.uname)
        add.addWidget(self.role)
        add.addWidget(add_btn)
        lay.addLayout(add)

        role_row = QHBoxLayout()
        self.role_uid = QLineEdit()
        self.role_uid.setPlaceholderText("要改角色的用户 ID")
        self.new_role = QComboBox()
        self.new_role.addItems(list(ROLES))
        role_btn = make_action_links([("设置角色", self._set_role)])
        role_row.addWidget(self.role_uid)
        role_row.addWidget(self.new_role)
        role_row.addWidget(role_btn)
        lay.addLayout(role_row)

        lay.addWidget(QLabel("集中配置 JSON（覆盖用户本地配置）:"))
        self.config = QTextEdit()
        self.config.setMinimumHeight(120)
        cfg_row = QHBoxLayout()
        save_cfg = QPushButton("保存集中配置")
        cfg_row.addWidget(save_cfg)
        cfg_row.addWidget(make_action_links([
            ("重新读取", self._load_config),
            ("📤 导出审计", self._export_audit),
        ]))
        cfg_row.addStretch(1)
        lay.addLayout(cfg_row)
        lay.addWidget(self.config)

        save_cfg.clicked.connect(self._save_config)
        self._refresh()

    def _refresh(self):
        r = self.store.list_users()
        users = r.get("users") or {}
        self.table.setRowCount(len(users))
        for row, (uid, u) in enumerate(sorted(users.items())):
            self.table.setItem(row, 0, QTableWidgetItem(uid))
            self.table.setItem(row, 1, QTableWidgetItem(str(u.get("name", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(u.get("role", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(
                "禁用" if u.get("disabled") else "启用"))
        self._load_config()

    def _add_user(self):
        r = self.store.add_user(self.uid.text().strip(), self.uname.text().strip(),
                                self.role.currentText())
        if not r.get("ok"):
            QMessageBox.warning(self, "团队", str(r.get("error") or r))
            return
        self.uid.clear()
        self.uname.clear()
        self._refresh()

    def _set_role(self):
        r = self.store.set_role(self.role_uid.text().strip(),
                                self.new_role.currentText())
        if not r.get("ok"):
            QMessageBox.warning(self, "团队", str(r.get("error") or r))
            return
        self._refresh()

    def _load_config(self):
        r = self.store.get_central_config()
        self.config.setPlainText(json.dumps(r.get("config") or {},
                                            ensure_ascii=False, indent=2))

    def _save_config(self):
        try:
            values = json.loads(self.config.toPlainText() or "{}")
        except Exception as e:
            QMessageBox.warning(self, "团队", "JSON 无效: " + str(e)[:100])
            return
        r = self.store.set_central_config(values)
        if not r.get("ok"):
            QMessageBox.warning(self, "团队", str(r.get("error") or r))
            return
        QMessageBox.information(self, "团队", "集中配置已保存，重启后全覆盖生效")

    def _export_audit(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出审计", "team_audit.json",
                                           "JSON (*.json)")
        if not p:
            return
        r = self.store.export_audit(p)
        if not r.get("ok"):
            QMessageBox.warning(self, "团队", str(r.get("error") or r))
            return
        QMessageBox.information(self, "团队", "已导出 %d 条审计" % r.get("count", 0))


def show_team_dialog(trunk, parent=None):
    d = TeamDialog(trunk, parent)
    d.exec_()
    return d
