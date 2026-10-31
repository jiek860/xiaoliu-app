# -*- coding: utf-8 -*-
"""多文件 diff 审批窗口。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QTextEdit, QPushButton, QMessageBox, QSplitter,
    QWidget, QPlainTextEdit,
)

from core.patch_engine import apply_patch, unified_diff, validate_patch
from gui.feedback_states import make_action_links


class DiffReviewDialog(QDialog):
    """展示 patch，允许按文件/按 hunk 接受，确认后应用。

    `patch` 格式见 core.patch_engine。窗口返回 accepted=True 时，
    `result` 为 apply_patch 的返回值。
    """

    def __init__(self, root, patch, parent=None, apply_on_accept=True):
        super().__init__(parent)
        self.root = root
        self.patch = validate_patch(root, patch)
        self.result = None
        self.selected_files = []
        self.selected_hunks = []
        self.apply_on_accept = bool(apply_on_accept)
        self.accepted = False
        self.setWindowTitle("AI 修改审批")
        self.resize(1000, 680)
        self._build()
        self._fill_tree()

    def _build(self):
        root = QVBoxLayout(self)
        self.goal = QLabel(self.patch.get("goal") or "待审批的文件修改")
        self.goal.setStyleSheet("font-size:15px;font-weight:700;")
        root.addWidget(self.goal)
        files = self.patch.get("files") or []
        hunks = sum(len(fp.get("hunks") or []) for fp in files)
        hint = QLabel("共 %d 个文件 / %d 个 hunk；勾选要应用的部分，"
                      "右侧预览会随选择变化。" % (len(files), hunks))
        hint.setStyleSheet("color:#667085;font-size:12px;")
        root.addWidget(hint)
        # 批次 O3：跨文件重构批次动辄十几个文件，给「全选 / 全不选」链接，
        # 不额外占按钮位（链接走统一样式与键盘可达）。
        root.addWidget(make_action_links([
            ("全选", lambda: self._check_all(Qt.Checked)),
            ("全不选", lambda: self._check_all(Qt.Unchecked)),
        ]))

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("文件 / hunk"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["修改", "原因"])
        self.tree.setColumnWidth(0, 260)
        self.tree.itemChanged.connect(lambda *_: self._preview())
        self.tree.itemClicked.connect(lambda *_: self._preview())
        ll.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("diff 预览"))
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        rl.addWidget(self.diff)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 620])
        root.addWidget(split, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(make_action_links([("取消", self.reject)]))
        apply = QPushButton("应用选中修改" if self.apply_on_accept else "批准这些修改")
        apply.setStyleSheet(
            "background:#4a9eff;color:white;border:none;border-radius:8px;"
            "padding:7px 14px;")
        apply.clicked.connect(self._apply)
        row.addWidget(apply)
        root.addLayout(row)

    def _fill_tree(self):
        self.tree.clear()
        for _fi, fp in enumerate(self.patch.get("files") or []):
            rel = fp.get("path", "")
            item = QTreeWidgetItem([rel, "文件"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable |
                          Qt.ItemIsAutoTristate)
            item.setCheckState(0, Qt.Checked)
            item.setData(0, Qt.UserRole, ("file", rel))
            self.tree.addTopLevelItem(item)
            for hi, h in enumerate(fp.get("hunks") or []):
                child = QTreeWidgetItem([
                    "hunk %d" % (hi + 1), h.get("reason", "")[:80]])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)
                child.setData(0, Qt.UserRole,
                              ("hunk", "%s:%d" % (rel, hi)))
                item.addChild(child)
            item.setExpanded(True)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._preview()

    def _check_all(self, state):
        """一键全选 / 全不选（含子 hunk），刷新预览。"""
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setCheckState(0, state)
            for j in range(item.childCount()):
                item.child(j).setCheckState(0, state)
        self.tree.blockSignals(False)
        self._preview()

    def _selection(self):
        files, hunks = [], []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            data = item.data(0, Qt.UserRole)
            child_hunks = []
            for j in range(item.childCount()):
                child = item.child(j)
                if child.checkState(0) == Qt.Checked:
                    child_hunks.append(child.data(0, Qt.UserRole)[1])
            # 允许只勾选部分 hunk：父文件即使 PartiallyChecked 也必须进入
            # selected_files，否则 apply_patch 会认为没有选中任何文件。
            if item.checkState(0) == Qt.Checked or child_hunks:
                files.append(data[1])
            hunks.extend(child_hunks)
        return files, hunks

    def _preview(self):
        files, hunks = self._selection()
        try:
            text = unified_diff(self.root, self.patch,
                                selected_files=files,
                                selected_hunks=hunks)
        except Exception as e:
            text = "diff 生成失败: " + str(e)[:300]
        self.diff.setPlainText(text or "（没有选中任何修改）")

    def _apply(self):
        files, hunks = self._selection()
        if not files:
            QMessageBox.information(self, "修改审批", "至少勾选一个文件")
            return
        # 新建 / 删除 / 重命名没有 hunk，只要勾了文件就可以批准；
        # 只有 update 需要 hunk，未勾任何 hunk 时这类文件不会产生改动。
        try:
            self.selected_files = files
            self.selected_hunks = hunks
            if self.apply_on_accept:
                self.result = apply_patch(
                    self.root, self.patch,
                    selected_files=files, selected_hunks=hunks)
            self.accepted = True
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "应用失败", str(e)[:400])
