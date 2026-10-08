# -*- coding: utf-8 -*-
"""历史记录窗口 - 分页/搜索/导出，独立于主聊天框"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QLineEdit, QMessageBox)
import os
from datetime import datetime

class HistoryDialog(QDialog):
    def __init__(self, trunk, account, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.account = account
        self.page_size = 50
        self.page = 0
        self.keyword = ""
        self.setWindowTitle("历史记录")
        self.resize(700, 600)
        self._build_ui()
        self._load_page()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索关键字（回车）")
        self.search.returnPressed.connect(self._do_search)
        top.addWidget(self.search, 1)
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._do_search)
        top.addWidget(btn_search)
        btn_clear = QPushButton("清空搜索")
        btn_clear.clicked.connect(self._clear_search)
        top.addWidget(btn_clear)
        layout.addLayout(top)
        self.view = QTextBrowser()
        self.view.setReadOnly(True)
        layout.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        self.info = QLabel("")
        bottom.addWidget(self.info, 1)
        self.prev_btn = QPushButton("更早")
        self.prev_btn.clicked.connect(self._prev)
        bottom.addWidget(self.prev_btn)
        self.next_btn = QPushButton("更新")
        self.next_btn.clicked.connect(self._next)
        bottom.addWidget(self.next_btn)
        btn_export = QPushButton("导出")
        btn_export.clicked.connect(self._export)
        bottom.addWidget(btn_export)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    def _all_msgs(self):
        try:
            return self.account.chat_store.export(self.account.username)
        except Exception:
            return []

    def _filter(self, msgs):
        if not self.keyword:
            return msgs
        k = self.keyword.lower()
        return [m for m in msgs if k in str(m.get("text", "")).lower()]

    def _load_page(self):
        msgs = self._filter(self._all_msgs())
        total = len(msgs)
        start = max(0, total - (self.page + 1) * self.page_size)
        end = total - self.page * self.page_size
        chunk = msgs[start:end]
        self.view.clear()
        for m in chunk:
            role = m.get("role", "")
            text = m.get("text", "")
            if role in ("u", "user"):
                self.view.append('<div style="color:#1976d2">用户:</div>')
                self.view.append('<div>' + text + '</div><br>')
            elif role in ("a", "assistant"):
                self.view.append('<div style="color:#7b1fa2">小6:</div>')
                self.view.append('<div>' + text + '</div><br>')
            else:
                self.view.append('<div>' + text + '</div><br>')
        self.info.setText("共 %d 条 · 第 %d 页 · 每页 %d 条" % (total, self.page + 1, self.page_size))
        self.prev_btn.setEnabled(end < total)
        self.next_btn.setEnabled(self.page > 0)

    def _prev(self):
        self.page += 1
        self._load_page()

    def _next(self):
        self.page = max(0, self.page - 1)
        self._load_page()

    def _do_search(self):
        self.keyword = self.search.text().strip()
        self.page = 0
        self._load_page()

    def _clear_search(self):
        self.search.clear()
        self.keyword = ""
        self.page = 0
        self._load_page()

    def _export(self):
        fn = os.path.join(self.trunk.base, "data",
                          "历史记录_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            with open(fn, "w", encoding="utf-8") as f:
                for m in self._filter(self._all_msgs()):
                    role = "用户" if m.get("role") in ("u", "user") else "小6"
                    f.write("%s: %s\n\n" % (role, m.get("text", "")))
            QMessageBox.information(self, "导出", "已保存到:\n" + fn)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e)[:80])
