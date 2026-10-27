# -*- coding: utf-8 -*-
"""RAG 管理窗口：导入文件/目录、ACL、来源列表、检索和引用预览。

交互约定（B8 批次）
------------------
· 导入在后台线程跑：整目录几十个 PDF 时窗口不能假死
· 导入结果给一句人话（新增/跳过/失败各多少），不再弹一坨 JSON
· 已索引来源用列表列出来，点一行就填进删除框（不用手打相对路径）
· 选择文件 / 选择目录 / 删除来源是低频动作 → 链接；按钮只留「导入」「搜索」
"""
from __future__ import annotations

import html
import os

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout,
)

from core.rag_pipeline import KnowledgeBase
from gui.feedback_states import make_action_links

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


class _IngestWorker(QThread):
    """后台导入：只碰 KnowledgeBase，不碰任何控件。"""

    done = pyqtSignal(object)

    def __init__(self, kb, path, roles):
        super().__init__()
        self.kb = kb
        self.path = path
        self.roles = list(roles or [])

    def run(self):
        try:
            if os.path.isdir(self.path):
                r = self.kb.ingest_directory(self.path, acl_roles=self.roles)
            else:
                r = self.kb.ingest_file(self.path, acl_roles=self.roles)
        except Exception as exc:
            r = {"ok": False, "error": str(exc)[:300]}
        self.done.emit(r)


def summarize_ingest(r):
    """把 ingest 的返回值翻译成一句人话（导入结果不该是 JSON）。"""
    if not isinstance(r, dict):
        return "导入失败：返回结果不可读"
    if "files" in r:
        results = r.get("results") or []
        fresh = [x for x in results if x.get("ok") and not x.get("skipped")]
        skipped = [x for x in results if x.get("skipped")]
        bad = [x for x in results if not x.get("ok")]
        msg = "✅ 新增/更新 %d 个 · 未变化跳过 %d 个" % (len(fresh), len(skipped))
        if bad:
            msg += " · ❌ 失败 %d 个" % len(bad)
            msg += "\n" + "\n".join(
                "%s：%s" % (x.get("source") or "?", x.get("error") or "未知错误")
                for x in bad[:5])
            if len(bad) > 5:
                msg += "\n… 还有 %d 个失败" % (len(bad) - 5)
        return msg
    if not r.get("ok"):
        return "❌ 导入失败：%s" % (r.get("error") or "未知错误")
    if r.get("skipped"):
        return "✓ 没有变化，跳过（%s，%d 块）" % (
            r.get("source"), int(r.get("chunks") or 0))
    return "✅ 已导入 %s：%d 块" % (r.get("source"), int(r.get("chunks") or 0))


class RAGDialog(QDialog):
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.base = getattr(trunk, "base", "") or "."
        self.namespace = str((getattr(trunk, "config", {}) or {}).get(
            "workspace_id", "default") or "default")
        self._worker = None
        self.setWindowTitle("RAG 知识库管理")
        self.resize(820, 720)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("工作区/命名空间:"))
        self.ns = QLineEdit(self.namespace)
        lay.addWidget(self.ns)
        self.stats = QLabel("")
        lay.addWidget(self.stats)

        lay.addWidget(QLabel("导入文档或目录:"))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("选一个文件或目录；支持 txt/md/pdf/docx/xlsx/pptx/html/csv")
        row.addWidget(self.path, 1)
        row.addWidget(make_action_links([
            ("选择文件", self._pick_file),
            ("选择目录", self._pick_dir),
        ]))
        self.ingest_btn = QPushButton("导入")
        self.ingest_btn.clicked.connect(self._ingest)
        row.addWidget(self.ingest_btn)
        lay.addLayout(row)

        acl_row = QHBoxLayout()
        acl_row.addWidget(QLabel("可访问角色（逗号分隔，留空=公开）:"))
        self.roles = QLineEdit("admin,editor,viewer")
        acl_row.addWidget(self.roles, 1)
        lay.addLayout(acl_row)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color:#475569;font-size:12px;")
        lay.addWidget(self.msg)

        lay.addWidget(QLabel("已索引来源（点一行 → 填进下面的删除框）:"))
        self.sources = QListWidget()
        self.sources.setMaximumHeight(110)
        self.sources.setToolTip("每个来源后面的数字是分块数")
        self.sources.itemClicked.connect(self._pick_source)
        lay.addWidget(self.sources)

        del_row = QHBoxLayout()
        self.del_source = QLineEdit()
        self.del_source.setPlaceholderText("要删除的来源相对路径，例如 docs/a.pdf")
        del_row.addWidget(self.del_source, 1)
        del_row.addWidget(make_action_links([("删除来源", self._delete)]))
        lay.addLayout(del_row)

        lay.addWidget(QLabel("检索（回车搜索；角色决定能看到哪些资料）:"))
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.role = QComboBox()
        self.role.addItems(["viewer", "editor", "admin", "auditor", "owner"])
        self.query.returnPressed.connect(self._search)
        # 搜索走「回车」+ 链接；按钮位留给「导入」这个主操作
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.role)
        search_row.addWidget(make_action_links([("搜索", self._search)]))
        lay.addLayout(search_row)

        self.results = QTextBrowser()
        self.results.setPlaceholderText("检索结果会显示在这里，带来源与页码引用")
        lay.addWidget(self.results, 1)

        self.query.returnPressed.connect(self._search)
        self._refresh()

    def _kb(self):
        return KnowledgeBase(self.base, self.ns.text().strip() or "default")

    def _refresh(self):
        try:
            kb = self._kb()
            s = kb.stats()
            self.stats.setText("来源 %d 个 · 分块 %d 个 · 清单 %d 个" % (
                s["sources"], s["chunks"], s["manifest_files"]))
            self.sources.clear()
            for item in kb.sources():
                text = "%s  (%d 块)" % (item["source"], item["chunks"])
                if item.get("acl_roles"):
                    text += "  🔒 " + "/".join(item["acl_roles"])
                self.sources.addItem(text)
            if not s["manifest_files"] and not self.msg.text():
                self.msg.setText(
                    "还没有资料：选一个文件或目录，点「导入」。"
                    "导入在后台跑，大目录也不会卡住窗口。")
        except Exception as e:
            self.stats.setText("统计失败: " + str(e)[:100])

    def _pick_source(self, item):
        text = item.text() if item is not None else ""
        self.del_source.setText(text.split("  (", 1)[0])

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
            self.msg.setText("先选择文件或目录（右边「选择文件 / 选择目录」）")
            return
        if self._worker is not None and self._worker.isRunning():
            self.msg.setText("正在导入，等这一轮结束再点")
            return
        try:
            kb = self._kb()
        except Exception as e:  # 静默是故意的 - 建库失败要显示给用户
            self.msg.setText("❌ 打不开这个命名空间：%s" % str(e)[:120])
            return
        if not os.path.exists(p):
            self.msg.setText("❌ 路径不存在：%s" % p)
            return
        self.msg.setText("⏳ 正在导入：%s" % os.path.basename(p.rstrip("\\/")))
        self.ingest_btn.setEnabled(False)
        worker = _IngestWorker(kb, p, self._roles())
        worker.done.connect(self._on_ingest_done)
        self._worker = worker
        worker.start()

    def _on_ingest_done(self, r):
        self.ingest_btn.setEnabled(True)
        self.msg.setText(summarize_ingest(r))
        self._refresh()

    def _search(self):
        q = self.query.text().strip()
        if not q:
            return
        try:
            hits = self._kb().search(q, top_k=8, role=self.role.currentText())
            if not hits:
                self.results.setHtml(
                    "<p>没有命中。可能原因：资料还没导入 / 换了角色 / 换个关键词。</p>")
                return
            parts = []
            for i, h in enumerate(hits, 1):
                parts.append("<h4>%d. %s</h4><p>%s</p>" % (
                    i, html.escape(str(h.get("citation") or "")),
                    html.escape(str(h.get("text") or "")[:1000])))
            self.results.setHtml("".join(parts))
        except Exception as e:
            self.results.setHtml("<p>搜索失败: %s</p>" % html.escape(str(e)[:120]))

    def _delete(self):
        source = self.del_source.text().strip()
        if not source:
            self.msg.setText("先从上面列表点一行，或手填来源相对路径")
            return
        if QMessageBox.question(self, "RAG", "删除来源 %s 的索引？" % source,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            ok = self._kb().delete_source(source)
            self._refresh()
            self.msg.setText("✅ 已删除 %s 的索引" % source if ok
                             else "没有找到该来源：%s（点上面的列表选）" % source)
        except Exception as e:
            self.msg.setText("❌ 删除失败：%s" % str(e)[:120])

    def closeEvent(self, event):
        """关窗时等后台导入收尾，避免线程还在写索引文件。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)
        self._worker = None
        try:
            super().closeEvent(event)
        except Exception as e:
            _x6_swallowed(__name__, e, "close rag dialog")


def show_rag_dialog(trunk, parent=None):
    d = RAGDialog(trunk, parent)
    d.exec_()
    return d
