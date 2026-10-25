# -*- coding: utf-8 -*-
"""小6 工作台：编辑器 + AI Agent 同屏（无页签）。

为什么这样设计
--------------
原来有三个独立窗口：代码编辑器 / Agent 旅程 / AI 代码 Agent。
用户改完 AI 生成的代码想手动微调，必须关掉一个再开另一个 —— 文件、目录、
选中片段全丢。而且三者重复实现了线程、diff 审批、时间线。

本工作台把三者放在**同一屏**：

    +------------------+------------------------------------+
    | 文件树            | 编辑器（多标签 = 多个文件，非功能页签） |
    |                  +------------------------------------+
    |                  | AI 面板（可折叠 / 可弹出为独立窗口）   |
    +------------------+------------------------------------+
    | 运行输出                                              |
    +-------------------------------------------------------+

* 没有"功能页签"：不存在"编辑器页/旅程页/Agent页"的切换
* 编辑器里的标签页只是**多个文件**，跟原来一样
* AI 面板与编辑器共享同一份"当前打开文件"上下文
* [弹出] 可把 AI 面板独立出去（双屏时贴到副屏），再点收回

兼容性：旧入口 open_code_editor / agent_journey_dialog / code_agent_dialog
全部改为打开本工作台并定位到对应区域，菜单文字与位置不变。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QMainWindow,
                             QSplitter, QVBoxLayout, QWidget)

# AI 面板在 gui/workbench_ai_dock.py（本文件曾接近 600 行上限）。
# 继续从这里导出 AgentDock，保持旧导入路径可用。
from gui.workbench_ai_dock import AgentDock  # noqa: F401

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


class WorkbenchWindow(QMainWindow):
    """统一工作台：编辑器 + AI 面板同屏，无功能页签。"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.root = os.path.abspath(
            getattr(trunk, "base", ".") or os.getcwd())
        self._ai_popup = None
        self._ai_placeholder = None
        self._ai_shown = True          # AI 面板默认展开
        self._editor = None
        self.setWindowTitle("🧰 小6 工作台")
        self.resize(1440, 900)
        self._build()

    # ---------------------------------------------------------- 构建
    def _build(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 顶部工具条：唯一的"打开 Agent"入口就用这里的 AI 面板，无需按钮切换
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 6, 8, 6)
        self.title = QLabel("🧰 工作台")
        self.title.setStyleSheet("font-weight:700;font-size:13px;")
        bar.addWidget(self.title)
        self.root_label = QLabel(os.path.basename(self.root) or self.root)
        self.root_label.setStyleSheet("color:#667085;font-size:11px;")
        self.root_label.setToolTip(self.root)
        bar.addWidget(self.root_label)
        bar.addStretch(1)
        hint = QLabel("Ctrl+J 收起 AI · F11 全屏 · 拖动分隔条调整比例")
        hint.setStyleSheet("color:#98a2b3;font-size:11px;")
        bar.addWidget(hint)
        # 收起/展开不占按钮：AI 面板是 splitter 的一部分，直接拖动分隔条即可；
        # 也支持 Ctrl+J 快捷键（见 _install_shortcuts）。
        self.collapse_btn = None
        v.addLayout(bar)

        # 主体：左文件树 | 右上编辑器 / 右下 AI
        self.splitter = QSplitter(Qt.Horizontal)
        self.editor_host = self._make_editor_host()
        self.splitter.addWidget(self.editor_host)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.vertical = QSplitter(Qt.Vertical)
        self.vertical.addWidget(self._make_editor_slot())
        self.ai_dock = AgentDock(self)
        self.vertical.addWidget(self.ai_dock)
        self.vertical.setSizes([620, 240])
        rv.addWidget(self.vertical, 1)
        self.splitter.addWidget(right)
        self.splitter.setSizes([280, 1160])
        v.addWidget(self.splitter, 1)
        self.setCentralWidget(central)
        self._install_shortcuts()

    def _install_shortcuts(self):
        """用快捷键替代按钮，减少界面控件数量。

        Ctrl+J  收起 / 展开 AI 面板
        F11     全屏切换
        """
        try:
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWidgets import QShortcut
            QShortcut(QKeySequence("Ctrl+J"), self, self.toggle_ai)
            QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        except Exception as e:  # 静默是故意的 - 快捷键装不上不影响使用
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _make_editor_host(self):
        """左：文件树（复用编辑器的实现）。"""
        return QWidget()

    def _make_editor_slot(self):
        """右上：嵌入 CodeEditorDialog 的编辑区。

        复用 CodeEditorDialog 而不是重写 —— 语法高亮、jedi 补全、
        多文件标签、运行输出都已经在里面验证过。
        """
        slot = QWidget()
        lay = QVBoxLayout(slot)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            from gui.code_editor_dialog import CodeEditorDialog
            self._editor = CodeEditorDialog(self.trunk, self)
            # 把它拆成"普通 QWidget"，这样能嵌进布局而不是独立窗口
            widget = self._editor.centralWidget()
            if widget is not None:
                lay.addWidget(widget)
                self._editor.setCentralWidget(QWidget())   # 解绑，避免重复父级
            else:
                lay.addWidget(self._editor)
        except Exception as e:  # 静默是故意的 - 编辑器坏了也不能让工作台打不开
            _x6_swallowed(__name__, e, "best-effort fallback")
            lay.addWidget(QLabel("编辑器加载失败：%s" % str(e)[:200]))
        return slot

    # ---------------------------------------------------------- 对外
    def editor_open_files(self):
        """当前编辑器里打开的所有文件路径（供 AI 参考）。"""
        out = []
        try:
            tabs = getattr(self._editor, "tabs", None)
            if tabs is None:
                return out
            for i in range(tabs.count()):
                w = tabs.widget(i)
                path = getattr(w, "filepath", "") or ""
                if path:
                    out.append(path)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return out

    def open_path(self, path):
        """供外部（菜单/聊天/AI）打开某个文件。"""
        try:
            if self._editor is not None and hasattr(self._editor, "open_path"):
                self._editor.open_path(path)
                return True
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        return False

    def show_diff_preview(self, root, patch, on_apply=None, on_undo=None):
        """编辑器内联 diff 预览（供 AI 面板 / 聊天调用）。"""
        try:
            if self._editor is not None and hasattr(self._editor, "show_diff_preview"):
                return self._editor.show_diff_preview(
                    root, patch, on_apply=on_apply, on_undo=on_undo)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show workbench diff preview")
        return None

    def mark_diff_applied(self, manifest=""):
        try:
            if self._editor is not None and hasattr(self._editor, "mark_diff_applied"):
                self._editor.mark_diff_applied(manifest)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "mark diff applied")

    def reload_editor_path(self, path):
        """Agent 落盘后刷新对应的打开 tab。"""
        root = getattr(self, "root", None) or "."
        if path and not os.path.isabs(str(path)):
            path = os.path.join(root, str(path))
        try:
            if self._editor is not None and hasattr(self._editor, "reload_path"):
                self._editor.reload_path(path)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "reload editor path")

    def set_goal(self, text):
        try:
            self.ai_dock.goal.setPlainText(str(text or ""))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    # ---------------------------------------------------------- AI 面板
    def toggle_ai(self):
        """收起 / 展开 AI 面板。

        ⚠️ 不能用 isVisible() 判断当前状态：窗口还没 show() 时它恒为 False，
           会导致第一次点击"收起"变成"展开"。这里用显式状态位。
        """
        shown = getattr(self, "_ai_shown", True)
        shown = not shown
        self._ai_shown = shown
        self.ai_dock.setVisible(shown)

    def toggle_ai_popup(self):
        """把 AI 面板弹出为独立窗口（可拖到第二块屏幕），再点收回。

        实现要点：QSplitter 的 widget 不能直接 takeChildren，
        必须用 replaceWidget 换成占位控件，否则 splitter 布局会崩。
        """
        if self._ai_popup is not None:
            self._close_ai_popup()
            return
        try:
            placeholder = QWidget()
            self.vertical.replaceWidget(1, placeholder)
            self._ai_placeholder = placeholder
            win = QMainWindow(self)
            win.setWindowTitle("🤖 AI 面板 · 小6")
            win.resize(560, 460)
            win.setCentralWidget(self.ai_dock)
            win.show()
            self._ai_popup = win
            self.ai_dock.expand_btn.setText("⛶ 收回")
        except Exception as e:  # 静默是故意的 - 弹出失败就保持内嵌
            _x6_swallowed(__name__, e, "best-effort fallback")

    def _close_ai_popup(self):
        """把 AI 面板收回工作台。"""
        try:
            win = self._ai_popup
            self._ai_popup = None
            if win is not None:
                win.setCentralWidget(QWidget())      # 先解绑，否则控件被带走
                win.close()
            placeholder = getattr(self, "_ai_placeholder", None)
            if placeholder is not None:
                self.vertical.replaceWidget(1, self.ai_dock)
                placeholder.deleteLater()
                self._ai_placeholder = None
            self.ai_dock.expand_btn.setText("⛶ 弹出")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        try:
            if self._ai_popup is not None:
                self._close_ai_popup()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        super().closeEvent(event)
