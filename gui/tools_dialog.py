# -*- coding: utf-8 -*-
"""v26-7.1: 日历+待办+笔记 统一工具对话框"""
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QTabWidget, QWidget, QMessageBox, QDateEdit
from PyQt5.QtCore import QDate

from gui.feedback_states import make_action_links


class ToolsDialog(QDialog):
    """日历/待办/笔记 统一面板"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("实用工具")
        self.setMinimumSize(600, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # 日历 tab
        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        row = QHBoxLayout()
        self.cal_title = QLineEdit()
        self.cal_title.setPlaceholderText("事件标题（回车添加）")
        self.cal_title.returnPressed.connect(self._add_cal)
        row.addWidget(self.cal_title)
        self.cal_date = QDateEdit()
        self.cal_date.setDate(QDate.currentDate())
        row.addWidget(self.cal_date)
        # 「添加」也可以直接敲回车 → 用链接表达，省一个按钮位
        row.addWidget(make_action_links([("添加", self._add_cal)]))
        row.addStretch(1)
        l1.addLayout(row)
        self.cal_list = QListWidget()
        l1.addWidget(self.cal_list)
        tabs.addTab(tab1, "日历")

        # 待办 tab
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        row2 = QHBoxLayout()
        self.todo_input = QLineEdit()
        self.todo_input.setPlaceholderText("待办事项（回车添加）")
        self.todo_input.returnPressed.connect(self._add_todo)
        row2.addWidget(self.todo_input)
        row2.addWidget(make_action_links([("添加", self._add_todo)]))
        row2.addStretch(1)
        l2.addLayout(row2)
        self.todo_list = QListWidget()
        l2.addWidget(self.todo_list)
        tabs.addTab(tab2, "待办")

        layout.addWidget(tabs)
        close_row = QHBoxLayout()
        close_row.addWidget(QLabel("Esc 关闭"))
        close_row.addStretch(1)
        layout.addLayout(close_row)

    def _add_cal(self):
        title = self.cal_title.text().strip()
        if not title:
            return
        date = self.cal_date.date().toString("yyyy-MM-dd")
        self.cal_list.addItem("%s %s" % (date, title))
        self.cal_title.clear()
        QMessageBox.information(self, "成功", "已添加事件")

    def _add_todo(self):
        text = self.todo_input.text().strip()
        if not text:
            return
        self.todo_list.addItem("☐ " + text)
        self.todo_input.clear()
