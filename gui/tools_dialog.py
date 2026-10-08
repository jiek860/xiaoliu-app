# -*- coding: utf-8 -*-
"""v26-7.1: 日历+待办+笔记 统一工具对话框"""
import os, json
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QListWidget, QTabWidget,
                             QWidget, QMessageBox, QDateEdit)
from PyQt5.QtCore import QDate


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
        self.cal_title.setPlaceholderText("事件标题")
        row.addWidget(self.cal_title)
        self.cal_date = QDateEdit()
        self.cal_date.setDate(QDate.currentDate())
        row.addWidget(self.cal_date)
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add_cal)
        row.addWidget(btn_add)
        l1.addLayout(row)
        self.cal_list = QListWidget()
        l1.addWidget(self.cal_list)
        tabs.addTab(tab1, "日历")

        # 待办 tab
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        row2 = QHBoxLayout()
        self.todo_input = QLineEdit()
        self.todo_input.setPlaceholderText("待办事项")
        row2.addWidget(self.todo_input)
        btn_todo = QPushButton("添加")
        btn_todo.clicked.connect(self._add_todo)
        row2.addWidget(btn_todo)
        l2.addLayout(row2)
        self.todo_list = QListWidget()
        l2.addWidget(self.todo_list)
        tabs.addTab(tab2, "待办")

        layout.addWidget(tabs)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

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
