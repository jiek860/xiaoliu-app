# -*- coding: utf-8 -*-
"""记忆可视化 - 时间线/图谱/搜索/编辑"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QTextBrowser, QLineEdit, QTabWidget, QWidget, QMessageBox, QInputDialog, QMenu
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links


class MemoryViewDialog(QDialog):
    """记忆可视化对话框"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("记忆可视化")
        self.setMinimumSize(860, 640)
        self.base = getattr(trunk, "base", None) or "."
        self.memory_path = os.path.join(self.base, "data", "memory_cards.jsonl")
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 标签页
        tabs = QTabWidget()

        # Tab1: 时间线
        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        self.timeline = QListWidget()
        self.timeline.setContextMenuPolicy(Qt.CustomContextMenu)
        self.timeline.customContextMenuRequested.connect(self._context_menu)
        l1.addWidget(self.timeline)
        tabs.addTab(tab1, "📅 时间线")

        # Tab2: 知识图谱
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        self.graph_tb = QTextBrowser()
        self.graph_tb.setReadOnly(True)
        l2.addWidget(self.graph_tb)
        tabs.addTab(tab2, "🕸️ 知识图谱")

        # Tab3: 搜索
        tab3 = QWidget()
        l3 = QVBoxLayout(tab3)
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索记忆关键词...")
        row.addWidget(self.search_input)
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._search)
        row.addWidget(btn_search)
        l3.addLayout(row)
        self.search_result = QTextBrowser()
        l3.addWidget(self.search_result)
        tabs.addTab(tab3, "🔍 搜索")

        layout.addWidget(tabs)

        # 底部：只留「搜索」一个按钮，导出/关闭走链接（按钮预算只许降）
        row = QHBoxLayout()
        row.addWidget(make_action_links([
            ("导出记忆", self._export),
            ("关闭", self.accept),
        ]))
        row.addStretch(1)
        row.addWidget(QLabel("Esc 关闭"))
        layout.addLayout(row)

    def _load_cards(self):
        cards = []
        if not os.path.exists(self.memory_path):
            return cards
        for ln in open(self.memory_path, encoding="utf-8"):
            try:
                cards.append(json.loads(ln.strip()))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
        return cards

    def _refresh(self):
        cards = self._load_cards()
        self.timeline.clear()
        for c in reversed(cards[-100:]):
            facts = "、".join(c.get("facts", []))
            date = c.get("date", c.get("time", "?"))
            item = QListWidgetItem("[%s] %s" % (date, facts[:80]))
            item.setData(Qt.UserRole, c)
            self.timeline.addItem(item)

        # 图谱（简化：显示所有实体关系）
        lines = []
        for c in cards[-50:]:
            for f in c.get("facts", []):
                lines.append("• " + f)
        self.graph_tb.setPlainText("\n".join(lines[-100:]) if lines else "暂无记忆数据")

    def _context_menu(self, pos):
        menu = QMenu(self)
        act_edit = menu.addAction("编辑")
        act_del = menu.addAction("删除")
        action = menu.exec_(self.timeline.mapToGlobal(pos))
        item = self.timeline.currentItem()
        if not item:
            return
        if action == act_edit:
            self._edit_item(item)
        elif action == act_del:
            self._delete_item(item)

    def _edit_item(self, item):
        c = item.data(Qt.UserRole)
        old = "、".join(c.get("facts", []))
        new, ok = QInputDialog.getText(self, "编辑记忆", "修改内容:", text=old)
        if ok and new:
            c["facts"] = [f.strip() for f in new.split("、") if f.strip()]
            self._rewrite_cards()
            self._refresh()

    def _delete_item(self, item):
        if QMessageBox.question(
            self, "确认删除", "删除这条记忆?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        row = self.timeline.row(item)
        cards = self._load_cards()
        if 0 <= row < len(cards):
            cards.pop(len(cards) - 1 - row)
            self._rewrite_cards(cards)
            self._refresh()

    def _rewrite_cards(self, cards=None):
        if cards is None:
            cards = self._load_cards()
        with open(self.memory_path, "w", encoding="utf-8") as f:
            for c in cards:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

    def _search(self):
        kw = self.search_input.text().strip()
        if not kw:
            return
        cards = self._load_cards()
        found = []
        for c in cards:
            text = json.dumps(c, ensure_ascii=False)
            if kw in text:
                found.append(c)
        lines = []
        for c in found[-20:]:
            facts = "、".join(c.get("facts", []))
            lines.append("[%s] %s\n" % (c.get("date", "?"), facts))
        self.search_result.setPlainText("\n".join(lines) if lines else "没找到相关记忆")

    def _export(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出记忆", "memory_export.json", "JSON (*.json)")
        if not path:
            return
        cards = self._load_cards()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "成功", "已导出 %d 条记忆" % len(cards))
