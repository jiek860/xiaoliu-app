# -*- coding: utf-8 -*-
"""保存链路：保存/另存为 + 保存即格式化（第 7 批 B4 + 深度④）。

从 `gui/code_editor_dialog.py` 搬出来（该文件到 600 行上限）。
搬家原则是"只搬不改"：`save_file` / `_save_w` / `save_as` / `_reload_patch_files`
行为逐字保留，只额外插了"保存前格式化"这一步。

为什么格式化要在这里做
--------------------
主流 IDE 的"保存即格式化"是在**写盘之前**把内容改成格式化结果，这样磁盘上
永远是格式化后的版本，而编辑器里那一次改动是**一个可撤销的编辑块**：
按一次 Ctrl+Z 就回到手写的样子。另外落盘前还会在 backups/format/ 留一份
快照 —— 万一撤销历史丢了，文件也能救回来。

没装格式化工具（black/ruff/prettier）时这一步**直接跳过**，保存照常完成。
"""
from __future__ import annotations

import os

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QFileDialog, QMessageBox

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class EditorSaveMixin:
    """CodeEditorDialog 的保存动作（保存时按需格式化）。"""

    def save_file(self):
        w = self._current_edit()
        if w:
            self._save_w(w)

    def _save_w(self, w):
        path = w.filepath
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存", "untitled.py", "Python (*.py)")
            if not path:
                return
        fmt = self._format_before_save(w, path)
        try:
            open(path, "w", encoding="utf-8").write(w.toPlainText())
            w.filepath = path
            w._dirty = False
            w.document().setModified(False)
            self._update_breadcrumb()
            try:
                if hasattr(self.trunk, "get_workspace_index"):
                    self.trunk.get_workspace_index().update_file(path)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            self.refresh_git_marks()
            note = ""
            if fmt.get("ok") and fmt.get("changed"):
                note = "（已用 %s 格式化，Ctrl+Z 可撤销）" % (
                    fmt.get("formatter") or "格式化工具")
            self._status("已保存: " + path + note, 3000)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def save_as(self):
        w = self._current_edit()
        if not w:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", "untitled.py", "Python (*.py)")
        if not path:
            return
        fmt = self._format_before_save(w, path)
        try:
            open(path, "w", encoding="utf-8").write(w.toPlainText())
            w.filepath = path
            w._dirty = False
            w.document().setModified(False)
            self._update_breadcrumb()
            note = ""
            if fmt.get("ok") and fmt.get("changed"):
                note = "（已用 %s 格式化）" % (fmt.get("formatter") or "格式化工具")
            self._status("已另存: " + path + note, 3000)
        except Exception as e:
            QMessageBox.warning(self, "另存失败", str(e))

    def _format_before_save(self, w, path=""):
        """保存前按 ``编辑.保存格式化`` 格式化；返回 {ok, changed, formatter}。

        整篇替换包在一个编辑块里 → 一次 Ctrl+Z 回到原样（验收要求"可撤销"）。
        """
        empty = {"ok": False, "changed": False, "formatter": "", "reason": ""}
        target = str(path or getattr(w, "filepath", "") or "")
        if not target:
            return empty
        try:
            from core.code_format import (format_on_save_enabled, format_preferred,
                                          format_text, snapshot_file)
        # 静默是故意的 - 格式化模块不可用就当没开这个功能
        except Exception as e:
            _x6_swallowed(__name__, e, "import code_format")
            return empty
        trunk = getattr(self, "trunk", None)
        root = getattr(self, "root", "") or ""
        try:
            if not format_on_save_enabled(trunk, target):
                return empty
            text = w.toPlainText()
            res = format_text(text, target, root=root,
                              preferred=format_preferred(trunk))
            if not res.get("ok") or not res.get("changed"):
                return res
            if root and getattr(w, "filepath", ""):
                snapshot_file(root, w.filepath, text)
            self._apply_formatted(w, res["text"])
            return res
        # 静默是故意的 - 格式化失败不挡保存，原文本照样落盘
        except Exception as e:
            _x6_swallowed(__name__, e, "format before save")
            return dict(empty, reason=str(e)[:150])

    @staticmethod
    def _apply_formatted(w, text):
        """把格式化结果写回编辑器（一个编辑块，一次撤销可退）。"""
        cur = QTextCursor(w.document())
        cur.beginEditBlock()
        cur.select(QTextCursor.Document)
        cur.insertText(str(text or ""))
        cur.endEditBlock()

    def _reload_patch_files(self, patch):
        """内联 diff 应用/撤销后重载受影响文件（等写盘完成再读）。"""
        root = getattr(self, "root", None) or os.getcwd()
        changes = (patch or {}).get("changes") or {}
        if not isinstance(changes, dict):
            return
        for rel in changes:
            path = rel if os.path.isabs(str(rel)) else os.path.join(
                root, str(rel))
            self.reload_path(path)

    def format_current_file(self, *_):
        """菜单/命令中心入口：格式化当前文件（保存格式化没开时也能手动用）。"""
        w = self._current_edit()
        if w is None:
            self._status("没有可格式化的文件", 3000)
            return {}
        res = w.lsp_format_document()
        if res.get("ok") and res.get("changed"):
            self._status("已格式化 %s" % os.path.basename(
                str(w.filepath or "当前文件")), 3000)
        return res
