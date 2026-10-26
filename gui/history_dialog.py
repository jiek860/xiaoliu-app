# -*- coding: utf-8 -*-
"""历史记录窗口 - 分页/搜索/导出，独立于主聊天框

这一轮修的三处：
    · 聊天存储读失败时静默返回空 → 界面显示"共 0 条"，用户以为消息丢了。
      现在把原因直接写在列表里。
    · 消息正文是按富文本直接塞进 QTextBrowser 的，用户发一句带 <b> 的内容
      就会改掉整页排版。现在统一 html.escape。
    · 翻页按钮用 end < total 判断"还有更早"，翻到底之后还能继续点，
      页码和条数对不上。改成按 start > 0 判断，页码显示 x/y。
"""
import html
import os
from datetime import datetime

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QLineEdit, QMessageBox)

from gui.feedback_states import make_action_links


class HistoryDialog(QDialog):
    def __init__(self, trunk, account, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.account = account
        self.page_size = 50
        self.page = 0
        self.keyword = ""
        self._error = ""
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
        top.addWidget(make_action_links([("清空搜索", self._clear_search)]))
        layout.addLayout(top)

        self.view = QTextBrowser()
        self.view.setReadOnly(True)
        layout.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.info = QLabel("")
        bottom.addWidget(self.info, 1)
        self.prev_btn = make_action_links([("◀ 更早", self._prev)])
        bottom.addWidget(self.prev_btn)
        self.next_btn = make_action_links([("更新 ▶", self._next)])
        bottom.addWidget(self.next_btn)
        bottom.addWidget(make_action_links([("📤 导出", self._export)]))
        bottom.addWidget(QLabel("Esc 关闭"))
        layout.addLayout(bottom)

    def _all_msgs(self):
        self._error = ""
        try:
            return self.account.chat_store.export(self.account.username) or []
        except Exception as e:
            self._error = "读取聊天记录失败：%s" % str(e)[:120]
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
        end = max(0, total - self.page * self.page_size)
        chunk = msgs[start:end] if end > start else []
        self.view.clear()
        if self._error:
            self.view.append('<div style="color:#b91c1c">%s</div>'
                             % html.escape(self._error))
        elif total == 0:
            hint = ("没有匹配「%s」的记录" % self.keyword
                    if self.keyword else "还没有聊天记录")
            self.view.append('<div style="color:#64748b">%s</div>'
                             % html.escape(hint))
        for m in chunk:
            role = m.get("role", "")
            text = html.escape(str(m.get("text", ""))).replace("\n", "<br>")
            if role in ("u", "user"):
                self.view.append('<div style="color:#1976d2">用户:</div>')
                self.view.append('<div>' + text + '</div><br>')
            elif role in ("a", "assistant"):
                self.view.append('<div style="color:#7b1fa2">小6:</div>')
                self.view.append('<div>' + text + '</div><br>')
            else:
                self.view.append('<div>' + text + '</div><br>')
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        self.info.setText("共 %d 条 · 第 %d/%d 页 · 每页 %d 条"
                          % (total, min(self.page + 1, pages), pages,
                             self.page_size))
        # 还有更早 = 这一页之前还有内容；还有更新 = 不是第 1 页
        self.prev_btn.setEnabled(start > 0)
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
        except Exception as e:
            QMessageBox.warning(
                self, "导出失败",
                "写不进 %s：%s\n检查 data 目录权限后重试。" % (fn, str(e)[:100]))
            return
        if self._error:
            QMessageBox.warning(self, "导出不完整", self._error)
            return
        QMessageBox.information(self, "导出", "已保存到:\n" + fn)
