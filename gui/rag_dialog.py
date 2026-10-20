# -*- coding: utf-8 -*-
"""RAG 管理窗口：导入文件/目录、ACL、检索和引用预览。"""
from __future__ import annotations

import html
import json
import os

from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextBrowser, QVBoxLayout,
)

from core.rag_pipeline import KnowledgeBase


class RAGDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.base = getattr(trunk, "base", "") or "."
        self.namespace = str((getattr(trunk, "config", {}) or {}).get(
            "workspace_id", "default") or "default")
        self.setWindowTitle("RAG 知识库管理")
        self.resize(760, 680)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("工作区/命名空间:"))
        self.ns = QLineEdit(self.namespace)
        lay.addWidget(self.ns)
        self.stats = QLabel("")
        lay.addWidget(self.stats)

        lay.addWidget(QLabel("导入文档或目录:"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        row.addWidget(self.path, 1)
        file_btn = QPushButton("选择文件")
        dir_btn = QPushButton("选择目录")
        ingest_btn = QPushButton("导入")
        for b in (file_btn, dir_btn, ingest_btn):
            row.addWidget(b)
        lay.addLayout(row)
        acl_row = QHBoxLayout()
        acl_row.addWidget(QLabel("可访问角色（逗号分隔，留空=公开）:"))
        self.roles = QLineEdit("admin,editor,viewer")
        acl_row.addWidget(self.roles, 1)
        lay.addLayout(acl_row)

        lay.addWidget(QLabel("检索:"))
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.role = QComboBox()
        self.role.addItems(["viewer", "editor", "admin", "auditor", "owner"])
        search_btn = QPushButton("搜索")
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.role)
        search_row.addWidget(search_btn)
        lay.addLayout(search_row)

        self.results = QTextBrowser()
        lay.addWidget(self.results, 1)

        del_row = QHBoxLayout()
        self.del_source = QLineEdit()
        self.del_source.setPlaceholderText("要删除的来源相对路径，例如 docs/a.pdf")
        del_btn = QPushButton("删除来源")
        del_row.addWidget(self.del_source, 1)
        del_row.addWidget(del_btn)
        lay.addLayout(del_row)

        file_btn.clicked.connect(self._pick_file)
        dir_btn.clicked.connect(self._pick_dir)
        ingest_btn.clicked.connect(self._ingest)
        search_btn.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        del_btn.clicked.connect(self._delete)
        self._refresh()

    def _kb(self):
        return KnowledgeBase(self.base, self.ns.text().strip() or "default")

    def _refresh(self):
        try:
            s = self._kb().stats()
            self.stats.setText("来源 %d 个 · 分块 %d 个 · 清单 %d 个" % (
                s["sources"], s["chunks"], s["manifest_files"]))
        except Exception as e:
            self.stats.setText("统计失败: " + str(e)[:100])

    def _pick_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择要导入的文档")
        if p:
            self.path.setText(p)

    def _pick_dir(self):
        p = QFileDialog.getExistingDirectory(self, "选择要导入的目录")
        if p:
            self.path.setText(p)

    def _roles(self):
        return [x.strip() for x in self.roles.text().split(",") if x.strip()]

    def _ingest(self):
        p = self.path.text().strip()
        if not p:
            QMessageBox.information(self, "RAG", "先选择文件或目录")
            return
        try:
            kb = self._kb()
            if os.path.isdir(p):
                r = kb.ingest_directory(p, acl_roles=self._roles())
            else:
                r = kb.ingest_file(p, acl_roles=self._roles())
            self._refresh()
            QMessageBox.information(self, "RAG", json.dumps(
                r, ensure_ascii=False, indent=2)[:1500])
        except Exception as e:
            QMessageBox.warning(self, "RAG", "导入失败: " + str(e)[:120])

    def _search(self):
        q = self.query.text().strip()
        if not q:
            return
        try:
            hits = self._kb().search(q, top_k=8, role=self.role.currentText())
            if not hits:
                self.results.setHtml("<p>没有命中，或当前角色无权查看。</p>")
                return
            parts = []
            for i, h in enumerate(hits, 1):
                parts.append("<h4>%d. %s</h4><p>%s</p><pre>%s</pre>" % (
                    i, html.escape(str(h.get("citation") or "")),
                    html.escape(str(h.get("text") or "")[:1000]),
                    html.escape(str(h.get("score")))))
            self.results.setHtml("".join(parts))
        except Exception as e:
            self.results.setHtml("<p>搜索失败: %s</p>" % html.escape(str(e)[:120]))

    def _delete(self):
        source = self.del_source.text().strip()
        if not source:
            return
        if QMessageBox.question(self, "RAG", "删除来源 %s 的索引？" % source,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            ok = self._kb().delete_source(source)
            self._refresh()
            QMessageBox.information(self, "RAG", "已删除" if ok else "没有找到该来源")
        except Exception as e:
            QMessageBox.warning(self, "RAG", "删除失败: " + str(e)[:120])


def show_rag_dialog(trunk, parent=None):
    d = RAGDialog(trunk, parent)
    d.exec_()
    return d
