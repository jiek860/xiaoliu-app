# -*- coding: utf-8 -*-
"""P1-14: 消息搜索对话框 - 全局搜索所有会话

交互取舍：搜索框回车即搜（returnPressed 已接），关闭交给 Esc。
所以这里不放「搜索 / 关闭」两个按钮 —— 纯展示弹窗不占按钮预算。
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox
)


class SearchDialog(QDialog):
    """全局消息搜索"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("🔍 搜索聊天记录")
        self.setMinimumSize(700, 500)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 搜索框（回车触发）
        row = QHBoxLayout()
        row.addWidget(QLabel("关键词:"))
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入搜索关键词，回车搜索（Esc 关闭）")
        self.input.returnPressed.connect(self._search)
        row.addWidget(self.input)
        layout.addLayout(row)

        # 结果列表
        self.result_list = QListWidget()
        layout.addWidget(self.result_list, stretch=1)

        hint = QLabel("回车搜索 · Esc 关闭")
        hint.setStyleSheet("color:#667085;font-size:11px;")
        layout.addWidget(hint)

    def _search(self):
        kw = self.input.text().strip()
        if not kw:
            return
        self.result_list.clear()
        try:
            chat_store = self.trunk.modules.get("chat_store")
            if not chat_store:
                QMessageBox.information(self, "提示", "聊天记录模块未加载")
                return
            # 调FTS搜索
            username = getattr(self.trunk, "current_user", "guest")
            results = chat_store.search(username, kw)
            for r in results[:50]:
                text = r.get("text", "")
                session = r.get("session_id", "")
                item = QListWidgetItem("[%s] %s" % (session, text[:100]))
                self.result_list.addItem(item)
            if self.result_list.count() == 0:
                self.result_list.addItem("没找到相关记录")
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e)[:100])
