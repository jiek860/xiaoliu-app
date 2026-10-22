# -*- coding: utf-8 -*-
"""P0-3: Trace 视图 - 任务时间树回看"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QTreeWidget,
    QTreeWidgetItem, QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt


class TraceViewDialog(QDialog):
    """Trace 时间树回看"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("📊 Trace 回看")
        self.setMinimumSize(900, 600)
        self._events = []
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 顶部：刷新 + 过滤
        row = QHBoxLayout()
        row.addWidget(QLabel("过滤:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("输入关键词过滤...")
        self.filter_input.textChanged.connect(self._render)
        row.addWidget(self.filter_input)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._load)
        row.addWidget(btn_refresh)
        layout.addLayout(row)

        # 分割器：左任务列表，右时间树
        splitter = QSplitter(Qt.Horizontal)

        # 左：任务列表
        left = QVBoxLayout()
        left.addWidget(QLabel("任务"))
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._on_task_selected)
        left.addWidget(self.task_list)
        from PyQt5.QtWidgets import QWidget
        lw = QWidget()
        lw.setLayout(left)
        splitter.addWidget(lw)

        # 右：时间树
        right = QVBoxLayout()
        right.addWidget(QLabel("时间线"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["时间", "事件", "详情"])
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 200)
        right.addWidget(self.tree)
        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)

        splitter.setSizes([250, 650])
        layout.addWidget(splitter, stretch=1)

        # 关闭按钮
        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _load(self):
        """从 data/traces/*.jsonl 读事件"""
        try:
            trace = self.trunk.modules.get("trace") if self.trunk else None
            if trace:
                self._events = trace.read(500)
            else:
                self._events = []
            self._render_tasks()
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e)[:100])

    def _render_tasks(self):
        """左列表：按 task_id 聚合"""
        self.task_list.clear()
        task_ids = []
        seen = set()
        for ev in self._events:
            tid = ev.get("task_id", "default")
            if tid not in seen:
                seen.add(tid)
                task_ids.append(tid)
        for tid in reversed(task_ids[-20:]):  # 最近 20 个
            item = QListWidgetItem(tid[:20])
            self.task_list.addItem(item)
        if self.task_list.count() > 0:
            self.task_list.setCurrentRow(0)

    def _on_task_selected(self, current, previous):
        self._render()

    def _render(self):
        """右树：选中任务的时间线"""
        self.tree.clear()
        item = self.task_list.currentItem()
        if not item:
            return
        tid = item.text()
        kw = self.filter_input.text().strip().lower()

        for ev in self._events:
            if ev.get("task_id", "default") != tid:
                continue
            if kw:
                txt = str(ev).lower()
                if kw not in txt:
                    continue
            time = ev.get("time", "")
            event = ev.get("event", ev.get("type", "?"))
            detail = str(ev.get("detail", ev.get("step", "")))[:100]
            node = QTreeWidgetItem([time, event, detail])
            # 失败标红
            if "fail" in event.lower() or "error" in event.lower():
                node.setForeground(0, Qt.red)
                node.setForeground(1, Qt.red)
            self.tree.addTopLevelItem(node)