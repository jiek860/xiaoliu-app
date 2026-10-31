# -*- coding: utf-8 -*-
"""P0-1: 深度研究对话框 - 多跳联网研究，带引用报告"""
import os
from html import escape as _html_escape

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QMessageBox, QInputDialog, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from gui.feedback_states import make_action_links

# B4：追问前缀（第二轮起自动带上上一轮主题，延续检索上下文）
_FOLLOWUPS = ("追问", "继续", "接着", "还有", "那")


class _ResearchWorker(QThread):
    """后台线程跑研究，不阻塞 UI"""
    done = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, trunk, topic):
        super().__init__()
        self.trunk = trunk
        self.topic = topic

    def run(self):
        try:
            dr = self.trunk.modules.get("deep_research")
            if not dr:
                self.failed.emit("deep_research 模块未加载")
                return
            result = dr.research(self.topic)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e)[:200])


class ResearchDialog(QDialog):
    """深度研究对话框"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("🔬 深度研究")
        self.setMinimumSize(900, 600)
        self._worker = None
        self._last_topic = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # 输入行
        row = QHBoxLayout()
        row.addWidget(QLabel("研究主题:"))
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入要研究的问题，如：PyQt5 最佳实践、RAG 框架对比...")
        self.input.returnPressed.connect(self._start)
        row.addWidget(self.input)
        self.btn_start = QPushButton("开始研究")
        self.btn_start.clicked.connect(self._start)
        row.addWidget(self.btn_start)
        layout.addLayout(row)

        # 分割器：左边报告，右边引用
        splitter = QSplitter(Qt.Horizontal)

        # 报告区
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("研究报告会显示在这里...")
        splitter.addWidget(self.report)

        # 引用列表
        right = QVBoxLayout()
        right.addWidget(QLabel("📚 引用来源"))
        self.ref_list = QListWidget()
        right.addWidget(self.ref_list)
        hint = QLabel("研究中可直接关闭窗口（Esc），不会卡界面")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#667085;font-size:11px;")
        right.addWidget(hint)
        from PyQt5.QtWidgets import QWidget
        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)

        splitter.setSizes([650, 250])
        layout.addWidget(splitter, stretch=1)

        # B4：导出报告（用链接，不加按钮，避免超按钮预算）
        layout.addWidget(make_action_links([
            ("📄 导出 Markdown", lambda: self._export("md")),
            ("🌐 导出 HTML", lambda: self._export("html")),
        ]))

    def _start(self):
        topic = self.input.text().strip()
        if not topic:
            QMessageBox.information(self, "提示", "请输入研究主题")
            return
        # 回车和「开始研究」是同一个入口，这里挡住重复触发
        if self._worker is not None and self._worker.isRunning():
            return
        # B4：追问 -> 带上上一轮主题，延续检索上下文
        if self._last_topic and topic.startswith(_FOLLOWUPS):
            topic = (self._last_topic + " " + topic).strip()
        # B4：主题太短 -> 先补一句背景（可跳过）
        elif len(topic) <= 6:
            extra, ok = QInputDialog.getText(
                self, "补充背景", "主题比较简短，补充一点背景/具体要求？",
                text=topic)
            if ok and extra.strip():
                topic = extra.strip()
        self._last_topic = topic
        self.btn_start.setEnabled(False)
        self.report.setPlainText("研究中...（最多 60 秒）")
        self.ref_list.clear()
        self._worker = _ResearchWorker(self.trunk, topic)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, result):
        self.btn_start.setEnabled(True)
        self.report.setPlainText(result.get("报告", ""))
        self.ref_list.clear()
        for s in result.get("引用", []):
            item = QListWidgetItem("[%d] %s\n    %s" % (s.get("ref", 0), s.get("标题", ""), s.get("链接", "")))
            self.ref_list.addItem(item)

    def _on_failed(self, msg):
        self.btn_start.setEnabled(True)
        self.report.setPlainText("研究失败: " + msg)

    def _export(self, fmt):
        """B4：把当前报告导出为 Markdown / HTML。"""
        text = self.report.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "还没有报告可导出")
            return
        ext = "md" if fmt == "md" else "html"
        default = os.path.join(os.path.expanduser("~"), "Desktop",
                               "研究报告." + ext)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出报告", default, "Markdown (*.md);;HTML (*.html)")
        if not path:
            return
        try:
            if fmt == "html":
                body = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        "<title>研究报告</title></head><body><pre>%s</pre>"
                        "</body></html>" % _html_escape(text))
            else:
                body = text
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            QMessageBox.information(self, "成功", "已导出：" + path)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e)[:120])
