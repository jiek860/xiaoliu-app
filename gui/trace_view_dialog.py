# -*- coding: utf-8 -*-
"""P0-3: Trace 视图 - 任务时间树回看"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QTreeWidget,
    QTreeWidgetItem, QSplitter, QMessageBox, QShortcut
)
from PyQt5.QtGui import QKeySequence
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

        # 顶部：过滤（F5 刷新，Esc 关闭 —— 不再各配一个按钮）
        row = QHBoxLayout()
        row.addWidget(QLabel("过滤:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("输入关键词过滤...")
        self.filter_input.textChanged.connect(self._render)
        row.addWidget(self.filter_input)
        hint = QLabel("F5 刷新 · Esc 关闭")
        hint.setStyleSheet("color:#667085;font-size:11px;")
        row.addWidget(hint)
        layout.addLayout(row)
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.activated.connect(self._load)

        # 概要：事件总数 / 失败数 / 总耗时 / 最慢几条（D3 统计，纯展示不加按钮）
        self.summary_label = QLabel("统计中...")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "color:#344054;background:#f8fafc;border:1px solid #e4e7ec;"
            "border-radius:6px;padding:6px 8px;font-size:12px;")
        layout.addWidget(self.summary_label)

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
        self.tree.setHeaderLabels(["时间", "事件", "耗时", "详情"])
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 180)
        self.tree.setColumnWidth(2, 80)
        right.addWidget(self.tree)
        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)

        splitter.setSizes([250, 650])
        layout.addWidget(splitter, stretch=1)
        # 关闭交给 Esc（QDialog 默认行为），不再单配一个按钮

    def _load(self):
        """从 data/traces/*.jsonl 读事件"""
        try:
            trace = self.trunk.modules.get("trace") if self.trunk else None
            if trace:
                self._events = trace.read(500)
            else:
                self._events = []
            self._render_tasks()
            self._update_summary()
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e)[:100])

    def _update_summary(self):
        """顶部概要：总数/失败/总耗时/最慢 Top3（失败链路一眼可见）"""
        try:
            from core.trace_stats import summary as _summary
            s = _summary(self._events, 3)
        except Exception as e:
            self.summary_label.setText("统计不可用：%s" % str(e)[:60])
            return
        slow = "、".join("%s %.0fms" % (x.get("component") or "?",
                                        x.get("dur_ms") or 0)
                        for x in s.get("slowest") or [])
        text = ("📈 共 %d 事件 · 失败 %d · 总耗时 %.0fms"
                % (s.get("count", 0), s.get("failures", 0), s.get("total_ms", 0)))
        if slow:
            text += "\n🐢 最慢: " + slow
        self.summary_label.setText(text)

    def _render_tasks(self):
        """左列表：按 task_id 聚合"""
        self.task_list.clear()
        task_ids = []
        counts = {}
        seen = set()
        for ev in self._events:
            tid = ev.get("task_id", "default")
            counts[tid] = counts.get(tid, 0) + 1
            if tid not in seen:
                seen.add(tid)
                task_ids.append(tid)
        for tid in reversed(task_ids[-20:]):  # 最近 20 个
            item = QListWidgetItem("%s (%d)" % (tid[:20], counts.get(tid, 0)))
            item.setData(Qt.UserRole, tid)
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
        tid = item.data(Qt.UserRole) or item.text()
        kw = self.filter_input.text().strip().lower()

        try:
            from core.trace_stats import dur_ms as _dur_ms
        except Exception:
            def _dur_ms(_ev):
                return 0.0

        for ev in self._events:
            if ev.get("task_id", "default") != tid:
                continue
            if kw:
                txt = str(ev).lower()
                if kw not in txt:
                    continue
            time = ev.get("time", "")
            # 真实事件（task_runtime）写的是 kind，回看窗口要能显示出来
            event = ev.get("event") or ev.get("type") or ev.get("kind") or "?"
            dur = _dur_ms(ev)
            dur_text = ("%.0fms" % dur) if dur > 0 else "-"
            detail = str(ev.get("detail", ev.get("step", "")))[:100]
            node = QTreeWidgetItem([time, event, dur_text, detail])
            # 失败标红（ok=False 或事件名带 fail/error）
            if (ev.get("ok") is False or "fail" in event.lower()
                    or "error" in event.lower()):
                node.setForeground(0, Qt.red)
                node.setForeground(1, Qt.red)
            self.tree.addTopLevelItem(node)
