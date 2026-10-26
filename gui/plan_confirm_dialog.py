# -*- coding: utf-8 -*-
"""计划确认对话框：让用户编辑/批准 coder_pro 的执行计划"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links


class PlanConfirmDialog(QDialog):
    """计划确认对话框：显示 AI 生成的计划，用户可以编辑后批准"""

    def __init__(self, plan_text, goal="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 确认执行计划")
        self.resize(700, 500)
        self._approved = False
        self._edited_plan = plan_text

        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("目标：" + goal))
        lay.addWidget(QLabel("请检查/编辑下面的计划，确认后点「开始执行」："))

        self.editor = QTextEdit()
        self.editor.setPlainText(plan_text)
        lay.addWidget(self.editor, stretch=1)

        row = QHBoxLayout()
        row.addWidget(make_action_links([("取消", self.reject)]))

        row.addStretch(1)

        approve = QPushButton("✅ 开始执行")
        approve.setStyleSheet("background:#10b981;color:white;padding:8px 20px;"
                              "border:none;border-radius:6px;")
        approve.clicked.connect(self._on_approve)
        row.addWidget(approve)
        lay.addLayout(row)

    def _on_approve(self):
        self._approved = True
        self._edited_plan = self.editor.toPlainText()
        self.accept()

    def is_approved(self):
        return self._approved

    def get_edited_plan(self):
        return self._edited_plan
