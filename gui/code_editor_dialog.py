# -*- coding: utf-8 -*-
"""CodeEditorDialog v2.0 - 小6内置完整版代码编辑器
布局：左资源管理器（文件操作在顶部） | 右面包屑 + 多标签编辑区 + 输出 | 状态栏
功能：
  - 多标签 / 行号 / Python 语法高亮 / 字体缩放
  - Tab 转 4 空格 / 自动缩进 / 实时语法错误下划线
  - jedi 自动补全
  - 文件树浏览 / 双击打开
  - 运行（QProcess）/ AI 修复（多轮）/ 右键"问小6"发回聊天
  - 编辑器工具条只留运行 / AI / 关闭，文件操作收进资源管理器顶部
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
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QTreeView, QFileSystemModel, QSplitter, QCompleter, QStatusBar, QDialog, QMenu
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QRect, QSize, QTimer
from PyQt5.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QTextDocument, QTextCursor, QPainter

from gui.feedback_states import make_action_links


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
    statusMessage = pyqtSignal(str)          # 工作台底部状态栏复用
    cursorMoved = pyqtSignal(int, int)       # 当前行/列（1-based）

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("📝 代码编辑器")
        self.resize(1100, 760)
        self._ai_history = []  # 多轮修复历史
        self._build_ui()
        # 默认打开一个新文件
        self.new_tab()

    def _tool_button(self, label, slot, tip, kind="flat", icon_only=False):
        """唯一的按钮创建点：文件操作/运行/AI/关闭都从这里出。

        icon_only=True 时只显示图标（资源管理器顶部一行），完整动作名放
        工具提示；这样侧栏窄也能放下，符合 IDE 的图标化工具栏习惯。
        """
        b = QPushButton(label)
        b.setFixedHeight(26 if icon_only else 28)
        if icon_only:
            b.setFixedWidth(26)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        _flat = (
            "QPushButton{background:transparent;color:#374151;"
            "border:1px solid transparent;border-radius:5px;"
            "padding:2px 6px;font-size:12px;text-align:center;}"
            "QPushButton:hover{background:#eaeef2;border-color:#d0d7de;}"
            "QPushButton:pressed{background:#dfe5eb;}")
        if kind == "run":
            css = (
                "QPushButton{background:#1f883d;color:#ffffff;"
                "border:1px solid #1a7f37;border-radius:5px;"
                "padding:3px 10px;font-size:12px;font-weight:600;"
                "text-align:center;}"
                "QPushButton:hover{background:#1a7f37;}"
                "QPushButton:pressed{background:#166f31;}")
        elif kind == "ai":
            css = (
                "QPushButton{background:#eef4ff;color:#1d4ed8;"
                "border:1px solid #c7d7fe;border-radius:5px;"
                "padding:3px 10px;font-size:12px;font-weight:600;"
                "text-align:center;}"
                "QPushButton:hover{background:#dbe8ff;border-color:#84adff;}")
        elif kind == "close":
            css = _flat.replace("color:#374151;", "color:#6b7280;")
        else:
            css = _flat
        b.setStyleSheet(css)
        b.clicked.connect(slot)
        return b

    def _build_ui(self):
        # 中心 splitter：左资源管理器 | 右（breadcrumb + tabs + 输出）
        splitter = QSplitter(Qt.Horizontal)
        # 左：文件树
        self.fs_model = QFileSystemModel()
        root = getattr(self.trunk, 'base', None) or os.getcwd()
        self.root = root
        self.fs_model.setRootPath(root)
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setRootIndex(self.fs_model.index(root))
        self.tree.setColumnWidth(0, 220)
        for i in (1, 2, 3):
            self.tree.hideColumn(i)
        # IDE 的树不显示 "Name" 表头，省一行高度
        self.tree.setHeaderHidden(True)
        self.tree.doubleClicked.connect(self._on_tree_dbl)

        # 资源管理器顶部：标题 + 文件操作图标（从编辑器工具条搬过来）
        tree_panel = QWidget()
        tl = QVBoxLayout(tree_panel)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        hdr_host = QWidget()
        hdr_host.setObjectName("explorerHeader")
        hdr_host.setAttribute(Qt.WA_StyledBackground, True)
        hdr_host.setStyleSheet(
            "QWidget#explorerHeader{background:#f6f8fa;"
            "border-bottom:1px solid #d0d7de;}")
        hdr = QHBoxLayout(hdr_host)
        hdr.setContentsMargins(6, 3, 4, 3)
        hdr.setSpacing(2)
        _explorer_title = QLabel("资源管理器")
        _explorer_title.setStyleSheet(
            "font-weight:600;font-size:12px;color:#24292f;")
        hdr.addWidget(_explorer_title)
        hdr.addStretch(1)
        hdr.addWidget(self._tool_button(
            "📄", self.new_tab, "新建标签页", icon_only=True))
        hdr.addWidget(self._tool_button(
            "📂", self.open_file, "打开文件", icon_only=True))
        hdr.addWidget(self._tool_button(
            "💾", self.save_file, "保存当前文件", icon_only=True))
        hdr.addWidget(self._tool_button(
            "📥", self.save_as, "另存为", icon_only=True))
        hdr.addWidget(make_action_links([("换目录", self._change_root)]))
        tl.addWidget(hdr_host)
        tl.addWidget(self.tree)
        splitter.addWidget(tree_panel)

        # 右：工具条 + 面包屑 + tabs + 输出
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        # 编辑器工具条只留"运行 / AI / 关闭"，文件操作已经在资源管理器顶部。
        tb_host = QWidget()
        tb_host.setObjectName("editorToolbar")
        tb_host.setAttribute(Qt.WA_StyledBackground, True)
        tb_host.setStyleSheet(
            "QWidget#editorToolbar{background:#f6f8fa;"
            "border-bottom:1px solid #d0d7de;}")
        tb = QHBoxLayout(tb_host)
        tb.setContentsMargins(8, 4, 8, 4)
        tb.setSpacing(2)
        tb.addWidget(self._tool_button(
            "▶ 运行", self.run_current, "运行当前文件", kind="run"))
        sep = QLabel()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet("background:#d0d7de;")
        tb.addSpacing(4)
        tb.addWidget(sep)
        tb.addSpacing(4)
        tb.addWidget(self._tool_button(
            "🔧 AI 修复", self.ai_fix, "把当前文件交给 AI 修复", kind="ai"))
        tb.addStretch(1)
        tb.addWidget(self._tool_button(
            "✕ 关闭", self.close_current_tab, "关闭当前标签页", kind="close"))
        rv.addWidget(tb_host)

        # 面包屑：当前文件相对工作区的路径
        self.breadcrumb = QLabel("📄 未保存")
        self.breadcrumb.setStyleSheet(
            "color:#57606a;font-size:11px;padding:3px 8px;"
            "background:#ffffff;border-bottom:1px solid #eaecf0;")
        rv.addWidget(self.breadcrumb)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:none;}"
            "QTabBar::tab{background:#f6f8fa;color:#57606a;padding:4px 12px;"
            "border:1px solid #d0d7de;border-bottom:none;"
            "border-top-left-radius:5px;border-top-right-radius:5px;"
            "margin-right:2px;}"
            "QTabBar::tab:selected{background:#ffffff;color:#1f2328;}")
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._update_breadcrumb)
        self.tabs.currentChanged.connect(self._update_cursor)
        # 右键菜单承载 PR 等低频操作（QAction 不占按钮预算）。
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tabs_menu)
        rv.addWidget(self.tabs, stretch=3)

        self.output_header = QLabel("▣ 输出")
        self.output_header.setStyleSheet(
            "background:#f6f8fa;color:#24292f;font-size:11px;"
            "font-weight:600;padding:3px 8px;border-top:1px solid #d0d7de;")
        rv.addWidget(self.output_header)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(180)
        self.output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas;"
            "font-size:12px;border:none;")
        rv.addWidget(self.output, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([260, 840])
        self.setCentralWidget(splitter)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")
        self._update_breadcrumb()
        self._update_cursor()

    def _update_cursor(self, *_):
        """把当前标签的光标位置发出去；非代码标签显示 0,0。"""
        try:
            w = self.tabs.currentWidget()
            if isinstance(w, CodeEditWidget):
                cur = w.textCursor()
                self.cursorMoved.emit(cur.blockNumber() + 1,
                                      cur.columnNumber() + 1)
            else:
                self.cursorMoved.emit(0, 0)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "update cursor position")

    def _emit_cursor(self, w):
        """只有当前标签的光标变化才更新工作台，后台标签不抢状态栏。"""
        try:
            if self.tabs.currentWidget() is w:
                cur = w.textCursor()
                self.cursorMoved.emit(cur.blockNumber() + 1,
                                      cur.columnNumber() + 1)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "emit cursor position")

    def _update_breadcrumb(self, *_):
        """文件路径面包屑：src › core › main.py；未保存时显示未保存。"""
        try:
            w = self.tabs.currentWidget()
            path = getattr(w, "filepath", "") if w is not None else ""
            if path:
                root = getattr(self, "root", os.getcwd())
                try:
                    rel = os.path.relpath(path, root)
                except Exception:
                    rel = path
                text = " › ".join(rel.replace("\\", "/").split("/"))
            else:
                text = "未保存"
            self.breadcrumb.setText("📄 " + text)
            self.breadcrumb.setToolTip(path or "未保存")
        except Exception as e:  # 静默是故意的 - 面包屑不能影响编辑
            _x6_swallowed(__name__, e, "update breadcrumb")

    def _status(self, message, timeout=0):
        """同时写编辑器状态栏和工作台底部状态栏（signal 供工作台复用）。"""
        try:
            self.statusBar().showMessage(message, timeout)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "editor status bar")
        try:
            self.statusMessage.emit(message)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "emit status message")

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
        w.cursorPositionChanged.connect(lambda w=w: self._emit_cursor(w))
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

    def close_current_tab(self):
        """IDE 习惯：编辑器右上角的 X 关当前标签，不关整个窗口。"""
        i = self.tabs.currentIndex()
        if i >= 0:
            self._close_tab(i)

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        if w is None:
            return
        if hasattr(w, "is_dirty") and w.is_dirty():
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

    def _tabs_menu(self, pos):
        w = self._current_edit()
        if w is None:
            return
        menu = QMenu(self)
        if w.filepath:
            act_save = menu.addAction("保存")
            act_save.triggered.connect(lambda: self._save_w(w))
            act_pr = menu.addAction("推送到 GitHub 并创建 PR")
            act_pr.triggered.connect(self._push_pr_current)
            menu.addSeparator()
        act_close = menu.addAction("关闭标签页")
        act_close.triggered.connect(
            lambda: self._close_tab(self.tabs.currentIndex()))
        menu.exec_(self.tabs.mapToGlobal(pos))

    def _push_pr_current(self):
        """把当前文件提交到功能分支并创建 PR（走 api.github.com）。"""
        w = self._current_edit()
        path = getattr(w, "filepath", "") if w else ""
        if not path:
            QMessageBox.information(self, "PR", "请先保存文件")
            return
        root = os.path.abspath(getattr(self.trunk, "base", ".") or ".")
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            from core.github_pr import PRFlow
            from PyQt5.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                r = PRFlow(self.trunk, root).run(
                    [(rel, w.toPlainText())],
                    title="chore: 更新 %s" % os.path.basename(path),
                    body="由小6代码编辑器发起", wait_ci=False)
            finally:
                QApplication.restoreOverrideCursor()
            if r.get("ok"):
                QMessageBox.information(
                    self, "已创建 PR",
                    "%s\n%s" % ((r.get("pr") or {}).get("url", ""),
                                "分支: " + str(r.get("branch"))))
            else:
                QMessageBox.warning(self, "PR 失败", str(r.get("error"))[:500])
        except Exception as e:  # 静默是故意的 - 失败必须告知用户
            QMessageBox.warning(self, "PR 失败", str(e)[:500])

    def open_path_at(self, path, line=1):
        """打开文件并定位到指定行（diff 预览跳转用）。"""
        if not path:
            return
        if not os.path.isabs(str(path)):
            root = getattr(self.trunk, "base", None) or os.getcwd()
            path = os.path.join(root, str(path))
        path = os.path.normpath(str(path))
        if not os.path.isfile(path):
            self._status("跳转失败，文件不存在: " + path, 4000)
            return
        self.open_path(path)
        w = self._current_edit()
        if not w:
            return
        block = w.document().findBlockByNumber(max(0, int(line or 1) - 1))
        if block.isValid():
            w.setTextCursor(QTextCursor(block))
            w.centerCursor()
            w.setFocus()
        self._status("已定位 %s:%s" % (
            os.path.basename(path), int(line or 1)), 3000)

    def show_diff_preview(self, root, patch, on_apply=None, on_undo=None):
        """在编辑器里打开内联 diff 预览 tab，返回 InlineDiffView。"""
        from gui.inline_diff import InlineDiffView
        view = InlineDiffView(root, patch, on_apply=on_apply,
                              on_undo=on_undo)
        view.jumpRequested.connect(self.open_path_at)
        title = "AI 修改预览"
        for i in range(self.tabs.count()):
            old = self.tabs.widget(i)
            if isinstance(old, InlineDiffView):
                self.tabs.removeTab(i)
                break
        idx = self.tabs.addTab(view, title)
        self.tabs.setCurrentIndex(idx)
        self._status("已生成内联 diff 预览，点击行可跳转", 4000)
        return view

    def mark_diff_applied(self, manifest=""):
        from gui.inline_diff import InlineDiffView
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, InlineDiffView):
                w.mark_applied(manifest)
                self.tabs.setCurrentIndex(i)

    def reload_path(self, path):
        """外部 Agent 改了文件后，刷新已打开的 tab（保留光标）。"""
        if not path:
            return
        path = os.path.normpath(str(path))
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditWidget) and \
                    os.path.normpath(str(w.filepath or "")) == path:
                try:
                    txt = open(path, encoding="utf-8").read()
                    if txt != w.toPlainText() and not w.is_dirty():
                        w.setPlainText(txt)
                        w._dirty = False
                except OSError:
                    return
                self.tabs.setCurrentIndex(i)
                return

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
            self._update_breadcrumb()
            try:
                if hasattr(self.trunk, "get_workspace_index"):
                    self.trunk.get_workspace_index().update_file(path)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            self._status("已保存: " + path, 3000)
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
                self._update_breadcrumb()
                self._status("已另存: " + path, 3000)
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
