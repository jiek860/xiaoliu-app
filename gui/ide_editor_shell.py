# -*- coding: utf-8 -*-
"""工作台编辑器外壳：标签栏 + 面包屑 + 编辑区、底部「输出/问题/终端」面板。

为什么不用 QTabWidget
--------------------
QTabWidget 把标签栏和内容区绑死，面包屑只能插在它上方（标签在下），
与 VS Code「标签在上、面包屑在下」相反。这里拆成
`QTabBar + 面包屑 + QStackedWidget`，对外仍暴露 QTabWidget 那套 API
（addTab/removeTab/widget/count/currentWidget/...），调用方不用改。

为什么单独一个文件
------------------
`code_editor_dialog.py` 已接近 600 行上限，标签栏 shim 和底部面板
都是纯 UI 零件，放这里更方便单独测试。

约束：不创建 QPushButton/QAction；页签是 QTabBar，动作走双击/回车。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QTextCharFormat
from PyQt5.QtWidgets import (QListWidget, QListWidgetItem, QPlainTextEdit,
                             QSplitter, QStackedWidget, QTabBar,
                             QVBoxLayout, QWidget)

from gui.ide_terminal import TerminalMixin

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


_TAB_QSS = (
    "QTabBar{background:#f6f8fa;}"
    "QTabBar::tab{background:#f6f8fa;color:#57606a;padding:4px 12px;"
    "border:1px solid #d0d7de;border-bottom:none;"
    "border-top-left-radius:5px;border-top-right-radius:5px;"
    "margin-right:2px;}"
    "QTabBar::tab:selected{background:#ffffff;color:#1f2328;}")


class EditorTabs(QWidget):
    """`QTabBar + 面包屑 + QStackedWidget`，兼容 QTabWidget 常用 API。

    header 会插在标签栏和内容区之间 —— 面包屑正好放这里。
    """

    currentChanged = pyqtSignal(int)
    tabCloseRequested = pyqtSignal(int)
    customContextMenuRequested = pyqtSignal(QPoint)

    def __init__(self, header=None, parent=None):
        super().__init__(parent)
        self.bar = QTabBar(self)
        self.bar.setDocumentMode(True)
        self.bar.setExpanding(False)
        self.bar.setMovable(True)
        self.bar.setElideMode(Qt.ElideRight)
        self.bar.setUsesScrollButtons(True)
        self.bar.setStyleSheet(_TAB_QSS)
        self.stack = QStackedWidget(self)
        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self.stack)
        self._secondary = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.bar)
        if header is not None:
            lay.addWidget(header)
        lay.addWidget(self._splitter, 1)
        self.bar.currentChanged.connect(self._on_bar_changed)
        self.bar.tabCloseRequested.connect(self.tabCloseRequested)
        self.bar.customContextMenuRequested.connect(
            self.customContextMenuRequested)

    # ---------------------------------------------------- QTabWidget 兼容
    def addTab(self, w, title):
        self.stack.addWidget(w)
        i = self.bar.addTab(str(title))
        if self.bar.count() == 1:
            self.stack.setCurrentIndex(0)
        self._align()
        return i

    def removeTab(self, i):
        if i < 0 or i >= self.stack.count():
            return
        w = self.stack.widget(i)
        self.stack.removeWidget(w)
        self.bar.removeTab(i)
        target = self.stack.currentIndex()
        if target < 0:
            target = 0 if self.stack.count() else -1
        if self.bar.count() and self.bar.currentIndex() != target:
            self.bar.setCurrentIndex(target)      # 触发 currentChanged
        else:
            self.stack.setCurrentIndex(target)
            self.currentChanged.emit(target)

    def widget(self, i):
        return self.stack.widget(i)

    def indexOf(self, w):
        return self.stack.indexOf(w)

    def count(self):
        return self.stack.count()

    def currentWidget(self):
        return self.stack.currentWidget()

    def currentIndex(self):
        return self.stack.currentIndex()

    def setCurrentIndex(self, i):
        if i < 0 or i >= self.bar.count():
            return
        self.bar.setCurrentIndex(i)               # 触发 currentChanged

    def setCurrentWidget(self, w):
        self.setCurrentIndex(self.indexOf(w))

    def setTabText(self, i, text):
        if 0 <= i < self.bar.count():
            self.bar.setTabText(i, str(text))

    def tabText(self, i):
        return self.bar.tabText(i) if 0 <= i < self.bar.count() else ""

    def setTabsClosable(self, on):
        self.bar.setTabsClosable(bool(on))

    def setDocumentMode(self, on):
        self.bar.setDocumentMode(bool(on))

    def setContextMenuPolicy(self, policy):
        self.bar.setContextMenuPolicy(policy)

    def mapToGlobal(self, pos):
        return self.bar.mapToGlobal(pos)

    def tabBar(self):
        return self.bar

    # ---------------------------------------------------- 分屏
    def set_secondary(self, w):
        """在编辑区右侧加第二个视图（分屏）。"""
        if w is None:
            return self.clear_secondary()
        if self._secondary is not None and self._secondary is not w:
            self._secondary.setParent(None)
        self._secondary = w
        self._splitter.addWidget(w)
        w.show()
        total = max(400, self.width())
        self._splitter.setSizes([total // 2, total // 2])
        return w

    def clear_secondary(self):
        w = self._secondary
        self._secondary = None
        if w is not None:
            w.setParent(None)
        self._splitter.setSizes([1, 0])
        return w

    def secondary(self):
        return self._secondary

    def has_secondary(self):
        return self._secondary is not None

    def _on_bar_changed(self, i):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
        self.currentChanged.emit(i)

    def _align(self):
        """标签和内容数量对齐时把两边索引同步一次。"""
        n = min(self.bar.count(), self.stack.count())
        if n and self.bar.currentIndex() != self.stack.currentIndex():
            self.stack.setCurrentIndex(max(0, self.bar.currentIndex()))


class BottomPanel(TerminalMixin, QWidget):
    """底部面板：输出（复用编辑器输出框） / 问题 / 终端 / 差异。"""

    jumpRequested = pyqtSignal(int)

    def __init__(self, output, root=".", parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root or os.getcwd())
        self.cwd = self.root
        self.bar = QTabBar(self)
        self.bar.setDocumentMode(True)
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setStyleSheet(
            _TAB_QSS.replace("padding:4px 12px", "padding:3px 10px"))
        self.bar.addTab("输出")
        self.bar.addTab("问题")
        self.bar.addTab("终端")
        self.stack = QStackedWidget(self)
        self.stack.addWidget(output)
        self.problems = QListWidget()
        self.problems.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;font-size:11px;}"
            "QListWidget::item{padding:3px 8px;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.problems.itemDoubleClicked.connect(self._open_problem)
        self.stack.addWidget(self.problems)
        self.stack.addWidget(self._build_terminal())
        self.bar.addTab("差异")
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(
            "background:#ffffff;color:#24292f;font-family:Consolas;"
            "font-size:12px;border:none;")
        self.stack.addWidget(self.diff)
        self.diff_index = self.bar.count() - 1
        self.bar.currentChanged.connect(self.stack.setCurrentIndex)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.bar)
        lay.addWidget(self.stack, 1)

    # ---------------------------------------------------- 问题页
    def set_problems(self, items):
        """问题页：兼容 (行, 描述) 与 (行, 列, 规则码, 描述) 两种写法。"""
        items = list(items or [])
        self.problems.clear()
        for entry in items:
            entry = tuple(entry or ())
            if not entry:
                continue
            try:
                line = int(entry[0] or 1)
            except (TypeError, ValueError):
                continue
            if len(entry) >= 4:
                col = int(entry[1] or 1)
                code = str(entry[2] or "")
                msg = str(entry[3] or "")
                text = "第 %d 行:%d  %s  %s" % (line, col, code, msg[:120])
            else:
                col, code, msg = 1, "", str(entry[1] if len(entry) > 1 else "")
                text = "第 %d 行  %s" % (line, msg[:120])
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, line)
            item.setToolTip("第 %d 行:%d  %s\n%s" % (line, col, code, msg))
            self.problems.addItem(item)
        self.bar.setTabText(1, "问题 %d" % len(items) if items else "问题")

    def _open_problem(self, item):
        line = item.data(Qt.UserRole)
        if line is not None:
            self.jumpRequested.emit(int(line))

    # ---------------------------------------------------- 差异页
    def show_diff(self, rel, text):
        """把 git diff 文本按 +/- 着色后放进「差异」页并切过去。"""
        try:
            name = os.path.basename(str(rel or "")) or "diff"
            self.diff.clear()
            cursor = self.diff.textCursor()
            for line in str(text or "").splitlines():
                first = line[:1]
                color = {"+": "#1a7f37", "-": "#cf222e",
                         "@": "#6e7781"}.get(first, "#24292f")
                if line.startswith(("+++", "---")):
                    color = "#6e7781"
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                cursor.insertText(line + "\n", fmt)
            self.bar.setTabText(self.diff_index, "差异 %s" % name[:24])
            self.select(self.diff_index)
            return text or ""
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show git diff")
            return ""

    # ---------------------------------------------------- 对外
    def add_extra_tab(self, title, widget):
        """挂一个额外页（如「测试」）：页签和内容区同步追加。"""
        self.bar.addTab(str(title))
        self.stack.addWidget(widget)
        return self.bar.count() - 1

    def select(self, index):
        if 0 <= index < self.bar.count():
            self.bar.setCurrentIndex(index)

    def current_index(self):
        return self.bar.currentIndex()
