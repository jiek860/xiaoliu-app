# -*- coding: utf-8 -*-
"""工作台外壳逻辑：状态栏、快捷键、AI 侧栏行为。

`gui/workbench_dialog.py` 被 `tests/test_module_split_exports.py` 要求
≤500 行，这里承接三块和布局无关、可单独验证的外壳逻辑：

  * WorkbenchStatusMixin：光标行列 / 语法错误数 / 当前文件与语言 / 快捷键
  * WorkbenchAIHostMixin：QDockWidget 的显隐、浮动、收回
  * WorkbenchSCMMixin：源代码管理视图的差异预览与提交回显

约定：不创建 QPushButton/QAction，也不改布局，按钮预算保持 60。
"""
from __future__ import annotations

import os

from gui.ide_sidebar import language_for_path

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


class WorkbenchStatusMixin:
    """把编辑器状态同步到工作台底部状态栏。"""

    def _wire_editor_status(self):
        """把编辑器的状态消息 / 当前文件同步到工作台底部。"""
        if self._editor is None:
            return
        try:
            self._editor.statusMessage.connect(self._on_editor_status)
            self._editor.cursorMoved.connect(self._on_cursor_moved)
            self._editor.syntaxErrorChanged.connect(self._on_syntax_errors)
            self._editor.tabs.currentChanged.connect(self._on_tab_changed)
            self._on_tab_changed(self._editor.tabs.currentIndex())
            self._editor._update_cursor()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "wire editor status")

    def _on_cursor_moved(self, line, col):
        if line and col:
            self.pos_label.setText("行 %d, 列 %d" % (line, col))
        else:
            self.pos_label.setText("行 -, 列 -")

    def _on_syntax_errors(self, count):
        n = int(count or 0)
        self.error_label.setText("⚠ %d" % n)
        self.error_label.setStyleSheet(
            "color:#cf222e;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;" if n else
            "color:#667085;font-size:11px;padding:0 8px;"
            "border-left:1px solid #d0d7de;")

    def _on_editor_status(self, message):
        self.status_label.setText(str(message or "就绪"))

    def _on_tab_changed(self, index):
        try:
            w = self._editor.tabs.widget(index)
            path = getattr(w, "filepath", "") if w is not None else ""
            if path:
                try:
                    rel = os.path.relpath(path, self.root)
                except Exception:
                    rel = path
                text = rel.replace("\\", "/")
            else:
                text = "未保存"
            self.path_label.setText(text + " · UTF-8 · LF")
            self.lang_label.setText(language_for_path(path))
            self._on_syntax_errors(getattr(w, "_syntax_errors", 0))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "workbench tab status")

    def _install_shortcuts(self):
        """用快捷键替代按钮，减少界面控件数量。

        Ctrl+J        收起 / 展开 AI 面板
        Ctrl+Shift+P  聚焦命令中心
        Ctrl+Shift+F  搜索工作区
        Ctrl+\\        编辑器分屏
        Ctrl+Shift+M  minimap 开关
        F11           全屏切换
        """
        try:
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWidgets import QShortcut
            QShortcut(QKeySequence("Ctrl+J"), self, self.toggle_ai)
            QShortcut(QKeySequence("Ctrl+Shift+P"), self, self._focus_command)
            QShortcut(QKeySequence("Ctrl+Shift+F"), self, self._show_search)
            QShortcut(QKeySequence("Ctrl+Shift+M"), self, self._toggle_minimap)
            QShortcut(QKeySequence("Ctrl+\\"), self, self._toggle_split)
            QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        except Exception as e:  # 静默是故意的 - 快捷键装不上不影响使用
            _x6_swallowed(__name__, e, "install workbench shortcuts")


class WorkbenchAIHostMixin:
    """AI 面板作为 QDockWidget 的显隐 / 浮动 / 收回。"""

    def _on_ai_visibility(self, visible):
        """QDockWidget 被用户关闭/打开时同步状态位。"""
        self._ai_shown = bool(visible)
        if not visible:
            try:
                self.activity_list.setCurrentRow(self._last_view_row)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "reset activity row")

    def toggle_ai(self):
        """收起 / 展开右侧 AI 面板（QDockWidget 的可见性）。

        ⚠️ 不能用 isVisible() 判断当前状态：窗口还没 show() 时它恒为 False，
           会导致第一次点击"收起"变成"展开"。这里用显式状态位。
        """
        shown = not getattr(self, "_ai_shown", True)
        self._ai_shown = shown
        self.ai_host.setVisible(shown)
        if shown and self.ai_host.isFloating():
            self.ai_host.show()
            self.ai_host.raise_()

    def toggle_ai_popup(self):
        """浮动 / 收回 AI 面板：QDockWidget 原生浮动窗口，可拖到第二块屏幕。"""
        if self._ai_popup is not None:
            return self._close_ai_popup()
        try:
            self.ai_host.setVisible(True)
            self.ai_host.setFloating(True)
            self.ai_host.resize(560, 460)
            self._ai_popup = self.ai_host
            self.ai_dock.expand_btn.setText("⛶ 收回")
        except Exception as e:  # 静默是故意的 - 浮动失败就保持内嵌
            _x6_swallowed(__name__, e, "float ai dock")

    def _close_ai_popup(self):
        """把浮动面板收回右侧栏。"""
        try:
            self.ai_host.setFloating(False)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "dock ai back")
        self._ai_popup = None
        self.ai_dock.expand_btn.setText("⛶ 弹出")


class WorkbenchSCMMixin:
    """源代码管理 → 底部「差异」页 + 提交结果回显。"""

    def _show_scm_diff(self, rel, text):
        """ScmPanel 发来的 diff 文本，直接送到底部差异页。"""
        try:
            ed = self._editor
            if ed is None or not hasattr(ed, "bottom"):
                return
            ed.bottom.show_diff(rel, text)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show scm diff")

    def _on_scm_commit_done(self, sha):
        """提交成功后把 sha 记到输出页，便于回查。"""
        try:
            ed = self._editor
            if ed is None or not hasattr(ed, "output"):
                return
            ed.output.appendPlainText("[git] 已提交 %s" % (sha or "OK"))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "scm commit done")
