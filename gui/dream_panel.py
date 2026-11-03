# -*- coding: utf-8 -*-
"""梦境面板：把 ``core.dream_system`` 的记录接到界面上。

为什么单独一个面板
------------------
``dream_system`` 原来只有能力表里的两个工具（``dream_recent`` /
``dream_make``），**界面上没有任何地方能看到** —— 用户不知道它做过梦。
这里挂在「记忆可视化」的「🌙 梦境」标签下，只展示 + 导出，
不新增按钮（动作走 ``make_action_links`` 的文字链接，按钮预算只许降）。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:      # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import (QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget)

from gui.feedback_states import make_action_links


class DreamPanel(QWidget):
    """梦境清单：最近做过的梦 + 做一个 + 导出 Markdown"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.view = QTextBrowser()
        layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(make_action_links([
            ("做个梦", self._make_dream),
            ("导出 Markdown", self._export),
            ("刷新", self.refresh),
        ]))
        row.addStretch(1)
        layout.addLayout(row)

    def _system(self):
        """拿 DreamSystem；模块已加载时复用，避免两份实例各写各的"""
        modules = getattr(self.trunk, "modules", None) or {}
        inst = modules.get("dream_system")
        if inst is not None:
            return inst
        from core.dream_system import DreamSystem
        return DreamSystem(self.trunk)

    # ------------------------------------------------------------------
    def refresh(self):
        try:
            self.view.setMarkdown(self._system().to_markdown(20))
        except Exception as e:
            _x6_swallowed(__name__, e, "refresh dreams")
            self.view.setPlainText("读取梦境失败：%s" % str(e)[:80])

    def _make_dream(self):
        try:
            entry = self._system().generate_dream()
        except Exception as e:
            _x6_swallowed(__name__, e, "make dream")
            self.view.setPlainText("做梦失败：%s" % str(e)[:80])
            return
        self.refresh()
        self.view.append("\n> 刚刚做的梦：%s" % str(entry.get("dream") or "")[:80])

    def _export(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, "导出梦境", "dreams.md",
                                              "Markdown (*.md)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._system().to_markdown(100))
        except Exception as e:
            QMessageBox.warning(self, "导出失败", "写入失败：%s" % str(e)[:80])
            return
        QMessageBox.information(self, "成功", "已导出: " + path)
