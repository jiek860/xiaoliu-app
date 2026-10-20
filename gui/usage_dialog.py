# -*- coding: utf-8 -*-
"""模型用量和成本估算面板。"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.model_pricing import format_cost
from core.usage_tracker import UsageTracker


class UsageDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.base = getattr(trunk, "base", "") or "."
        self.setWindowTitle("模型用量与成本")
        self.resize(760, 500)
        lay = QVBoxLayout(self)
        self.summary = QLabel("")
        lay.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["模型", "调用", "成功/失败", "Token", "成本(估算)", "P95 延迟"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.refresh()

    def refresh(self):
        tracker = UsageTracker(self.base)
        s = tracker.summary(days=7)
        self.summary.setText(
            "最近 7 天：%d 次调用 · %d tokens · 估算成本 %s · 总耗时 %.1fs" % (
                s["calls"], s["tokens_in"] + s["tokens_out"],
                format_cost(s["cost"]), s["elapsed"]))
        by_model = tracker.model_stats(days=7)
        self.table.setRowCount(len(by_model))
        for row, (model, m) in enumerate(sorted(by_model.items())):
            values = [model, str(m["calls"]), "%d/%d" % (m["ok"], m["fail"]),
                      str(m["tokens"]), format_cost(m["cost"]), "%.2fs" % m["p95"]]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))


def show_usage_dialog(trunk, parent=None):
    d = UsageDialog(trunk, parent)
    d.exec_()
    return d
