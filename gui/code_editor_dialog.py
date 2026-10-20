# -*- coding: utf-8 -*-
"""CodeEditorDialog v2.0 - 小6内置完整版代码编辑器
布局：左文件树 | 右多标签编辑区 | 底运行输出 | 状态栏
功能：
  - 多标签 / 行号 / Python 语法高亮 / 字体缩放
  - Tab 转 4 空格 / 自动缩进 / 实时语法错误下划线
  - jedi 自动补全
  - 文件树浏览 / 双击打开
  - 运行（QProcess）/ AI 修复（多轮）/ 右键"问小6"发回聊天
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import sys
import ast
import tempfile
import difflib
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QTreeView, QFileSystemModel, QSplitter, QCompleter, QStatusBar, QDialog
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QRect, QSize, QTimer
from PyQt5.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QTextDocument, QTextCursor, QPainter


# ============ Python 语法高亮 ============


# ============ 行号区域 ============


# ============ 单标签编辑组件 ============


# ============ 主窗口 ============
from gui.code_editor_widget import (
    CodeEditWidget, _LineNumberArea, _PyHighlighter,
)
from gui.code_editor_ai import CodeEditorAIMixin
from gui.code_editor_runner import CodeEditorRunnerMixin


class CodeEditorDialog(CodeEditorAIMixin, CodeEditorRunnerMixin, QMainWindow):
    askAssistantRequested = pyqtSignal(str)  # 发回小6聊天框

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("📝 代码编辑器")
        self.resize(1100, 760)
        self._ai_history = []  # 多轮修复历史
        self._build_ui()
        # 默认打开一个新文件
        self.new_tab()

    def _build_ui(self):
        # 中心 splitter：左文件树 | 右（tabs + 输出）
        splitter = QSplitter(Qt.Horizontal)
        # 左：文件树
        self.fs_model = QFileSystemModel()
        root = getattr(self.trunk, 'base', None) or os.getcwd()
        self.fs_model.setRootPath(root)
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setRootIndex(self.fs_model.index(root))
        self.tree.setColumnWidth(0, 220)
        for i in (1, 2, 3):
            self.tree.hideColumn(i)
        self.tree.doubleClicked.connect(self._on_tree_dbl)
        # 换根按钮
        tree_panel = QWidget(); tl = QVBoxLayout(tree_panel); tl.setContentsMargins(4,4,4,4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("📂"))
        btn_root = QPushButton("换目录"); btn_root.clicked.connect(self._change_root)
        bar.addWidget(btn_root)
        tl.addLayout(bar); tl.addWidget(self.tree)
        splitter.addWidget(tree_panel)

        # 右：上 tabs / 下输出
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0)
        # 工具条
        tb = QHBoxLayout()
        for label, slot in [("📄 新建", self.new_tab), ("📂 打开", self.open_file),
                            ("💾 保存", self.save_file), ("💾 另存为", self.save_as),
                            ("▶ 运行", self.run_current),
                            ("🔧 AI 修复", self.ai_fix),
                            ("✕ 关闭", self.close)]:
            b = QPushButton(label); b.setStyleSheet("padding:4px 10px;")
            b.clicked.connect(slot); tb.addWidget(b)
        tb.addStretch(1)
        rv.addLayout(tb)

        self.tabs = QTabWidget(); self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        rv.addWidget(self.tabs, stretch=3)

        rv.addWidget(QLabel("📟 运行输出："))
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        self.output.setMaximumHeight(180)
        self.output.setStyleSheet("background:#1e1e1e;color:#d4d4d4;font-family:Consolas;font-size:12px;")
        rv.addWidget(self.output, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([260, 840])
        self.setCentralWidget(splitter)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    def _change_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择项目根目录")
        if d:
            self.fs_model.setRootPath(d)
            self.tree.setRootIndex(self.fs_model.index(d))

    def _on_tree_dbl(self, idx):
        path = self.fs_model.filePath(idx)
        if os.path.isfile(path):
            self.open_path(path)

    def _new_edit(self):
        w = CodeEditWidget()
        w.askAssistantRequested.connect(self.askAssistantRequested.emit)
        return w

    def new_tab(self):
        w = self._new_edit()
        idx = self.tabs.addTab(w, "未保存")
        self.tabs.setCurrentIndex(idx)
        w.textChanged.connect(lambda: self._update_tab_title(w))

    def _update_tab_title(self, w):
        i = self.tabs.indexOf(w)
        if i < 0: return
        name = os.path.basename(w.filepath) if w.filepath else "未保存"
        if w.is_dirty():
            name = "● " + name
        self.tabs.setTabText(i, name)

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        if w.is_dirty():
            r = QMessageBox.question(self, "未保存", "当前文件有改动，保存？",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Save:
                self._save_w(w)
            elif r == QMessageBox.Cancel:
                return
        self.tabs.removeTab(i)

    def _current_edit(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditWidget) else None

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开", "", "Python (*.py);;所有文件 (*.*)")
        if path: self.open_path(path)

    def open_path(self, path):
        # 已开则切过去
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditWidget) and w.filepath == path:
                self.tabs.setCurrentIndex(i); return
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e)); return
        w = self._new_edit(); w.setPlainText(txt); w.filepath = path
        i = self.tabs.addTab(w, os.path.basename(path))
        self.tabs.setCurrentIndex(i)

    def save_file(self):
        w = self._current_edit()
        if w: self._save_w(w)

    def _save_w(self, w):
        path = w.filepath
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存", "untitled.py", "Python (*.py)")
            if not path: return
        try:
            open(path, "w", encoding="utf-8").write(w.toPlainText())
            w.filepath = path
            w._dirty = False
            try:
                if hasattr(self.trunk, "get_workspace_index"):
                    self.trunk.get_workspace_index().update_file(path)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            self.statusBar().showMessage("已保存: " + path, 3000)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def save_as(self):
        w = self._current_edit()
        if not w: return
        path, _ = QFileDialog.getSaveFileName(self, "另存为", "untitled.py", "Python (*.py)")
        if path:
            try:
                open(path, "w", encoding="utf-8").write(w.toPlainText())
                w.filepath = path; w._dirty = False
            except Exception as e:
                QMessageBox.warning(self, "另存失败", str(e))

    def set_code(self, code, title="未命名"):
        """聊天框把 AI 给的代码送进来：新起一个 tab"""
        w = self._new_edit(); w.setPlainText(code or "")
        i = self.tabs.addTab(w, title)
        self.tabs.setCurrentIndex(i)
        self.show(); self.raise_(); self.activateWindow()

    def current_code(self):
        w = self._current_edit()
        return w.toPlainText() if w else ""
