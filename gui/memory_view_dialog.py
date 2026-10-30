# -*- coding: utf-8 -*-
"""记忆可视化 - 时间线/图谱/搜索/编辑"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os, json, time, hashlib
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget, QListWidgetItem, QTextBrowser, QLineEdit, QTabWidget, QWidget, QMessageBox, QInputDialog, QMenu
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links
from gui.chat_growth_panel import GrowthPanel


def load_cards(path):
    """读记忆卡；坏行跳过，不抛异常（批次 43.4 逻辑层）。"""
    cards = []
    if not os.path.exists(path):
        return cards
    try:
        with open(path, encoding="utf-8") as fp:
            lines = fp.readlines()
    except OSError as e:
        _x6_swallowed(__name__, e, "load_cards")
        return cards
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            card = json.loads(line)
        except (ValueError, TypeError) as e:
            _x6_swallowed(__name__, e, "bad_card")
            continue
        if isinstance(card, dict):
            cards.append(card)
    return cards


def save_cards(path, cards):
    """原子写回：先写 .tmp 再 replace；失败返回 False。"""
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            for card in cards or []:
                fp.write(json.dumps(card, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        return True
    except Exception as e:
        _x6_swallowed(__name__, e, "save_cards")
        return False


def display_text(card):
    """v2 卡用 text，旧卡用 facts 拼一行。"""
    if not isinstance(card, dict):
        return ""
    text = str(card.get("text") or "").strip()
    if text:
        return text
    return "、".join(str(f) for f in (card.get("facts") or []) if str(f).strip())


def visible_cards(cards, limit=100):
    """返回 [(原始下标, 卡)]，只取最近 limit 条，供列表倒序展示。"""
    cards = list(cards or [])
    start = max(0, len(cards) - max(1, int(limit or 100)))
    return list(enumerate(cards))[start:]


def edit_card(card, new_text, *, now=None):
    """纠正一条记忆：更新 text/facts 与稳定 id；空内容返回原卡。"""
    text = str(new_text or "").strip()
    if not isinstance(card, dict) or not text:
        return card
    edited = dict(card)
    edited["text"] = text
    if "facts" in edited:
        edited["facts"] = [text]
    try:
        from core.chat.memory_v2 import card_id
        edited["id"] = card_id(text)
    except Exception:
        edited["id"] = "m_" + hashlib.sha1(
            text.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    edited["updated_at"] = float(now or time.time())
    return edited


def delete_card(cards, index):
    """按下标删除并返回新列表；越界原样返回。"""
    cards = list(cards or [])
    try:
        index = int(index)
    except (TypeError, ValueError):
        return cards
    if 0 <= index < len(cards):
        cards.pop(index)
    return cards


def search_cards(cards, keyword):
    kw = str(keyword or "").strip()
    if not kw:
        return []
    return [c for c in (cards or []) if kw in json.dumps(c, ensure_ascii=False)]


def export_cards(path, cards):
    """导出为 JSON 数组；返回条数，失败返回 -1。"""
    try:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(list(cards or []), fp, ensure_ascii=False, indent=2)
        return len(cards or [])
    except Exception as e:
        _x6_swallowed(__name__, e, "export_cards")
        return -1


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

        self.growth = GrowthPanel(self.trunk, self)
        tabs.addTab(self.growth, "🌱 成长")

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
        return load_cards(self.memory_path)

    def _date_text(self, card):
        value = card.get("date", card.get("time", "?"))
        if isinstance(value, (int, float)) and value > 0:
            try:
                return time.strftime("%Y-%m-%d", time.localtime(value))
            except (OSError, ValueError):
                return "?"
        return str(value or "?")

    def _refresh(self):
        cards = self._load_cards()
        self.timeline.clear()
        for index, c in reversed(visible_cards(cards)):
            text = display_text(c)
            item = QListWidgetItem("[%s] %s" % (self._date_text(c), text[:80]))
            item.setData(Qt.UserRole, c)
            item.setData(Qt.UserRole + 1, index)
            self.timeline.addItem(item)

        # 图谱（简化：显示所有实体关系）
        lines = []
        for c in cards[-50:]:
            text = display_text(c)
            if text:
                lines.append("• " + text)
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
        index = item.data(Qt.UserRole + 1)
        old = display_text(c)
        new, ok = QInputDialog.getText(self, "编辑记忆", "修改内容:", text=old)
        if not (ok and str(new or "").strip()):
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        cards = self._load_cards()
        if 0 <= index < len(cards):
            cards[index] = edit_card(cards[index], new)
            if not self._rewrite_cards(cards):
                QMessageBox.warning(self, "保存失败", "记忆文件写入失败，请稍后再试")
        self._refresh()

    def _delete_item(self, item):
        if QMessageBox.question(
            self, "确认删除", "删除这条记忆?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        try:
            index = int(item.data(Qt.UserRole + 1))
        except (TypeError, ValueError):
            return
        cards = delete_card(self._load_cards(), index)
        if not self._rewrite_cards(cards):
            QMessageBox.warning(self, "删除失败", "记忆文件写入失败，请稍后再试")
        self._refresh()

    def _rewrite_cards(self, cards=None):
        if cards is None:
            cards = self._load_cards()
        return save_cards(self.memory_path, cards)

    def _search(self):
        kw = self.search_input.text().strip()
        if not kw:
            return
        found = search_cards(self._load_cards(), kw)
        lines = []
        for c in found[-20:]:
            lines.append("[%s] %s\n" % (self._date_text(c), display_text(c)))
        self.search_result.setPlainText("\n".join(lines) if lines else "没找到相关记忆")

    def _export(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出记忆", "memory_export.json", "JSON (*.json)")
        if not path:
            return
        count = export_cards(path, self._load_cards())
        if count >= 0:
            QMessageBox.information(self, "成功", "已导出 %d 条记忆" % count)
        else:
            QMessageBox.warning(self, "导出失败", "写入导出文件失败")
