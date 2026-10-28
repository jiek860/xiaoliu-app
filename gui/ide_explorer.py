# -*- coding: utf-8 -*-
"""资源管理器增强：Git 状态着色 + 右键新建/重命名/删除/定位。

为什么单独一个文件
------------------
`ide_sidebar.py` 负责活动栏图标和侧栏视图，已经接近 600 行上限；
文件树的 Git 模型和右键菜单只依赖 QFileSystemModel，拆出来更清晰。

约束：右键菜单只用 `QMenu.addAction`，不新建 QAction 实例，
按钮预算仍是 60。宿主窗口需要提供 `tree / fs_model / root /
open_path / _status`。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (QFileSystemModel, QInputDialog, QMenu,
                             QMessageBox)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


def git_status_entries(root):
    """`git status --porcelain` → [(状态, 相对路径)]；没有 git 时返回 None。"""
    try:
        # core.quotePath=false：否则 git 会把中文路径输出成
        # `"docs/\344\270\255..."`，既对不上文件树的真实路径（不着色），
        # 也会让 SCM 列表显示乱码。
        cp = subprocess.run(
            ["git", "-c", "core.quotePath=false", "status", "--porcelain"],
            cwd=root, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=5)
        if cp.returncode != 0:
            return None
        out = []
        for ln in (cp.stdout or "").splitlines():
            if len(ln) <= 3:
                continue
            status = ln[:2].strip() or "?"
            rel = ln[3:].strip().split(" -> ")[-1].strip('"')
            out.append((status, rel))
        return out
    except Exception as e:  # 静默是故意的 - 没有 git 就当作无改动
        _x6_swallowed(__name__, e, "git status")
        return None


def git_status_map(root):
    """绝对路径 → 状态字符，供文件树着色用。"""
    entries = git_status_entries(root)
    if entries is None:
        return {}
    base = os.path.abspath(root or ".")
    return {os.path.normpath(os.path.join(base, rel)): status
            for status, rel in entries}


class GitFileModel(QFileSystemModel):
    """文件树模型：给改动过的文件加 Git 状态颜色（VS Code 资源管理器风格）。

    只覆盖 ForegroundRole（文件名颜色），不动图标/列/排序；
    状态来自 `git status --porcelain`，用 green/amber/red/gray 区分 A/M/D/?。
    """

    STATUS_COLORS = {"M": "#9a6700", "A": "#1a7f37", "?": "#6e7781",
                     "D": "#cf222e", "R": "#8250df", "U": "#cf222e",
                     "C": "#1a7f37"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = {}

    def refresh_git(self, root=None, mapping=None):
        if mapping is None:
            mapping = git_status_map(root or self.rootPath())
        self._status = {os.path.normcase(os.path.normpath(p)): s
                        for p, s in mapping.items()}
        return len(self._status)

    def git_status_for(self, path):
        if not path:
            return ""
        key = os.path.normcase(os.path.normpath(str(path)))
        return self._status.get(key, "")

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.ForegroundRole and index.column() == 0:
            status = self.git_status_for(self.filePath(index))
            if status:
                color = self.STATUS_COLORS.get(status.strip()[:1], "#6e7781")
                return QBrush(QColor(color))
        return super().data(index, role)


def reveal_in_explorer(path):
    """在系统文件管理器里定位到该文件（跨平台）。"""
    try:
        target = os.path.normpath(str(path))
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", target])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(target)])
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "reveal in explorer")


class ExplorerMenuMixin:
    """资源管理器右键菜单：新建文件/文件夹、重命名、删除、定位。"""

    def refresh_git_marks(self):
        try:
            self.fs_model.refresh_git(self.root)
            self.tree.viewport().update()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "refresh git marks")

    def _tree_menu(self, pos):
        try:
            idx = self.tree.indexAt(pos)
            path = self.fs_model.filePath(idx) if idx.isValid() else self.root
            is_dir = os.path.isdir(path)
            parent = path if is_dir else os.path.dirname(path)
            menu = QMenu(self.tree)
            act_file = menu.addAction("新建文件")
            act_dir = menu.addAction("新建文件夹")
            act_rename = menu.addAction("重命名") if path else None
            act_delete = None
            if path and os.path.abspath(path) != os.path.abspath(self.root):
                act_delete = menu.addAction("删除")
            menu.addSeparator()
            act_reveal = menu.addAction("在资源管理器中显示")
            chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
            if chosen == act_file:
                self._create_entry(parent, make_dir=False)
            elif chosen == act_dir:
                self._create_entry(parent, make_dir=True)
            elif act_rename is not None and chosen == act_rename:
                self._rename_entry(path)
            elif act_delete is not None and chosen == act_delete:
                self._delete_entry(path)
            elif chosen == act_reveal:
                reveal_in_explorer(path)
        except Exception as e:  # 静默是故意的 - 菜单失败不能影响编辑
            _x6_swallowed(__name__, e, "explorer context menu")

    def _create_entry(self, parent_dir, make_dir=False):
        title = "新建文件夹" if make_dir else "新建文件"
        name, ok = QInputDialog.getText(self, title, "名称：")
        name = (name or "").strip()
        if not ok or not name:
            return
        path = os.path.join(parent_dir, name)
        try:
            if make_dir:
                os.makedirs(path, exist_ok=True)
            else:
                if not os.path.exists(path):
                    open(path, "w", encoding="utf-8").close()
                self.open_path(path)
            self.refresh_git_marks()
            self._status("%s：%s" % (title, name), 3000)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e)[:200])

    def _rename_entry(self, path):
        old = os.path.basename(path)
        name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=old)
        name = (name or "").strip()
        if not ok or not name or name == old:
            return
        new = os.path.join(os.path.dirname(path), name)
        if os.path.exists(new):
            QMessageBox.information(self, "重命名", "目标已存在：%s" % name)
            return
        try:
            os.rename(path, new)
            self.refresh_git_marks()
            self._status("已重命名：%s" % name, 3000)
        except Exception as e:
            QMessageBox.warning(self, "重命名失败", str(e)[:200])

    def _delete_entry(self, path):
        name = os.path.basename(path)
        r = QMessageBox.question(
            self, "删除", "确定删除 %s ？" % name,
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            self.refresh_git_marks()
            self._status("已删除：%s" % name, 3000)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e)[:200])
