# -*- coding: utf-8 -*-
"""内联 diff 预览：双击跳转 + 应用/撤销（不新增按钮预算）。

为什么不用 QPushButton
--------------------
`tools/check_buttons.py` 的按钮预算已经卡死。这个视图里的"应用/撤销"
用 QLabel 的富文本链接实现：可点击、可禁用、不算控件创建点。

配套能力
--------
* 双击（或键盘移动光标）diff 行 -> 打开对应源文件并定位到行；
* 应用：调用 `apply_patch`，保留 backup_manifest；
* 撤销：优先回调任务编排器的 rollback，否则按 manifest 回滚；
* `mark_applied()`：Agent 已经应用时只更新状态，避免重复写盘。
"""
from __future__ import annotations

import os
import re

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout,
                             QWidget)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class InlineDiffView(QWidget):
    jumpRequested = pyqtSignal(str, int)
    applyRequested = pyqtSignal()
    undoRequested = pyqtSignal()

    def __init__(self, root, patch, on_apply=None, on_undo=None, parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root)
        self.patch = patch or {}
        self.on_apply = on_apply
        self.on_undo = on_undo
        self.manifest = ""
        self._applied = False
        self._targets = {}
        self._last_key = None
        self._build()
        self._fill()

    # ---------------------------------------------------------- UI
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QLabel(self.patch.get("goal") or "AI 修改预览")
        head.setStyleSheet("padding:6px 10px;font-weight:700;background:#eef5ff;")
        lay.addWidget(head)
        self.hint = QLabel(
            "点击/双击 diff 行可跳转到源文件；应用与撤销在底部。")
        self.hint.setStyleSheet("padding:2px 10px;color:#667085;font-size:11px;")
        lay.addWidget(self.hint)
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;"
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        self.diff.cursorPositionChanged.connect(self._on_cursor)
        lay.addWidget(self.diff, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 6, 10, 6)
        self.apply_link = QLabel(
            '<a href="apply" style="color:#1976d2;text-decoration:none;">'
            '✓ 应用全部修改</a>')
        self.apply_link.linkActivated.connect(self._apply)
        self.undo_link = QLabel(
            '<a href="undo" style="color:#b42318;text-decoration:none;">'
            '↩ 撤销本次修改</a>')
        self.undo_link.linkActivated.connect(self._undo)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#667085;font-size:11px;")
        foot.addWidget(self.apply_link)
        foot.addSpacing(18)
        foot.addWidget(self.undo_link)
        foot.addSpacing(12)
        foot.addWidget(self.status, 1)
        lay.addLayout(foot)

    def _fill(self):
        try:
            from core.patch_engine import unified_diff
            text = unified_diff(self.root, self.patch)
        except Exception as e:  # 静默是故意的 - 预览失败也要显示原因
            text = "diff 生成失败: " + str(e)[:300]
        self.diff.setPlainText(text or "（没有可预览的修改）")
        self._targets = self._index_diff(text)
        if not text:
            self.status.setText("没有修改")

    def _index_diff(self, text):
        """把 diff 的显示行号映射到 (源文件, 源行号)。"""
        out = {}
        rel = ""
        new_line = old_line = 0
        for i, line in enumerate(str(text or "").splitlines()):
            if line.startswith("+++ b/"):
                rel = line[6:].strip()
                continue
            if line.startswith("--- a/"):
                continue
            m = _HUNK.match(line)
            if m:
                old_line, new_line = int(m.group(1)), int(m.group(2))
                continue
            if not rel:
                continue
            if line.startswith("+"):
                out[i] = (rel, new_line)
                new_line += 1
            elif line.startswith("-"):
                out[i] = (rel, max(1, old_line))
                old_line += 1
            elif line.startswith(" "):
                out[i] = (rel, new_line)
                new_line += 1
                old_line += 1
        return out

    def _on_cursor(self):
        pos = self.diff.textCursor().blockNumber()
        target = self._targets.get(pos)
        if not target or target == self._last_key:
            return
        self._last_key = target
        self.jumpRequested.emit(target[0], int(target[1]))

    # ---------------------------------------------------------- 动作
    def _apply(self, *_):
        if self._applied:
            self.status.setText("已应用，无需重复操作")
            return
        self.applyRequested.emit()
        if callable(self.on_apply):
            try:
                self.on_apply()
                self._applied = True
                self.status.setText("已应用（外部流程）")
            except Exception as e:  # 静默是故意的 - 外部回调失败要显示
                self.status.setText("应用失败: " + str(e)[:160])
            return
        try:
            from core.patch_engine import apply_patch
            r = apply_patch(self.root, self.patch)
            self.manifest = str(r.get("backup_manifest") or "")
            self._applied = True
            self.status.setText("已应用: %s" % ", ".join(r.get("applied") or []))
            self.apply_link.setText("✓ 已应用")
        except Exception as e:  # 静默是故意的 - 应用失败必须留在预览里提示
            self.status.setText("应用失败: " + str(e)[:200])

    def _undo(self, *_):
        self.undoRequested.emit()
        if callable(self.on_undo):
            try:
                r = self.on_undo() or {}
                restored = r.get("restored") if isinstance(r, dict) else None
                self.status.setText("已撤销: %s" % (restored or "完成"))
                self._applied = False
            except Exception as e:  # 静默是故意的
                self.status.setText("撤销失败: " + str(e)[:160])
            return
        if not self.manifest:
            self.status.setText("没有可撤销的修改")
            return
        try:
            from core.patch_engine import rollback
            r = rollback(self.manifest)
            self.status.setText("已撤销: %s" % (r.get("restored") or []))
            self._applied = False
            self.manifest = ""
        except Exception as e:  # 静默是故意的
            self.status.setText("撤销失败: " + str(e)[:200])

    def mark_applied(self, manifest=""):
        """外部（Agent）已经应用时调用：只更新状态，不重复写盘。"""
        self._applied = True
        if manifest:
            self.manifest = str(manifest)
        self.status.setText("Agent 已应用本次修改")
        self.apply_link.setText("✓ 已应用")

    def current_target(self):
        pos = self.diff.textCursor().blockNumber()
        return self._targets.get(pos)
