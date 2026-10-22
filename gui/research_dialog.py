# -*- coding: utf-8 -*-
"""P0-1: 深度研究对话框 - 多跳联网研究，带引用报告"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal


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
        right_widget = QPushButton("关闭")
        right.addWidget(right_widget)
        right_widget.clicked.connect(self.accept)
        from PyQt5.QtWidgets import QWidget
        rw = QWidget()
        rw.setLayout(right)
        splitter.addWidget(rw)

        splitter.setSizes([650, 250])
        layout.addWidget(splitter, stretch=1)

    def _start(self):
        topic = self.input.text().strip()
        if not topic:
            QMessageBox.information(self, "提示", "请输入研究主题")
            return
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