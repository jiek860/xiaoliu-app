# -*- coding: utf-8 -*-
"""工作台源代码管理视图（ScmPanel）与侧栏共用的小样式。

为什么单独一个文件
------------------
`gui/ide_sidebar.py` 在加上「暂存 / 提交 / 差异」后越过 600 行硬上限
（`tools/check_file_sizes.py`），所以把 Git 视图和它依赖的侧栏头部
样式一起搬到这里，`ide_sidebar` 只做 re-export（旧导入路径不变）。

约束：本文件不创建 QPushButton/QToolButton/QCheckBox/QAction，
交互一律用 QLabel 链接 / QLineEdit / QMenu.addAction。
"""
from __future__ import annotations

import os
import subprocess

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QVBoxLayout,
                             QWidget)

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None

from gui.ide_explorer import git_status_entries  # noqa: E402


# git status 首字母 -> 颜色（和文件树保持一致）
_SCM_COLORS = {"M": "#9a6700", "A": "#1a7f37", "D": "#cf222e",
               "R": "#8250df", "C": "#8250df", "U": "#cf222e",
               "?": "#6e7781"}

_HEADER_QSS = (
    "QWidget#sideHeader{background:#f6f8fa;border-bottom:1px solid #d0d7de;}")
_HEADER_TITLE_QSS = "font-weight:600;font-size:12px;color:#24292f;"
_HINT_QSS = "color:#667085;font-size:11px;"


def _header(title):
    """侧栏小标题栏：左标题 + 右侧可挂链接。"""
    host = QWidget()
    host.setObjectName("sideHeader")
    host.setAttribute(Qt.WA_StyledBackground, True)
    host.setStyleSheet(_HEADER_QSS)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(8, 4, 6, 4)
    lab = QLabel(title)
    lab.setStyleSheet(_HEADER_TITLE_QSS)
    lay.addWidget(lab)
    lay.addStretch(1)
    return host, lay


class ScmPanel(QWidget):
    """源代码管理：分支 + 改动列表 + 暂存/提交/差异预览。

    交互全部用 QLabel 链接 / QLineEdit / QMenu.addAction ——
    按钮预算已满 60，本视图不新增任何创建点。
    """

    openRequested = pyqtSignal(str)
    diffRequested = pyqtSignal(str, str)   # (相对路径, 差异文本)
    commitDone = pyqtSignal(str)           # 提交成功后的短 sha

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root or os.getcwd())
        self._build()
        self.refresh()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head, hl = _header("源代码管理")
        stage_all = QLabel('<a href="stage" style="color:#1d4ed8;'
                           'font-size:11px;text-decoration:none;">全部暂存</a>')
        stage_all.setToolTip("git add -A：把全部改动加入暂存区")
        stage_all.linkActivated.connect(lambda *_: self.stage_all())
        hl.addWidget(stage_all)
        refresh = QLabel('<a href="refresh" style="color:#1d4ed8;'
                         'font-size:11px;text-decoration:none;">刷新</a>')
        refresh.linkActivated.connect(self.refresh)
        hl.addWidget(refresh)
        v.addWidget(head)

        self.branch = QLabel("分支：-")
        self.branch.setStyleSheet(
            "color:#475467;font-size:11px;padding:5px 8px;"
            "border-bottom:1px solid #eaecf0;")
        v.addWidget(self.branch)

        self.msg = QLineEdit()
        self.msg.setPlaceholderText("提交信息，Enter 提交")
        self.msg.setToolTip("填好信息按 Enter，提交已暂存的改动")
        self.msg.setFixedHeight(28)
        self.msg.setStyleSheet(
            "QLineEdit{padding:0 6px;border:1px solid #d0d7de;"
            "border-radius:5px;background:#ffffff;font-size:12px;}")
        self.msg.returnPressed.connect(self._commit_from_box)
        row = QHBoxLayout()
        row.setContentsMargins(8, 6, 8, 0)
        row.setSpacing(6)
        row.addWidget(self.msg, 1)
        commit = QLabel('<a href="commit" style="color:#1d4ed8;'
                        'font-size:11px;text-decoration:none;">提交</a>')
        commit.setToolTip("提交已暂存的改动")
        commit.linkActivated.connect(lambda *_: self._commit_from_box())
        row.addWidget(commit)
        v.addLayout(row)

        self.changes = QListWidget()
        self.changes.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;}"
            "QListWidget::item{padding:4px 8px;border-bottom:1px solid #f2f4f7;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.changes.itemDoubleClicked.connect(self._open_item)
        self.changes.setContextMenuPolicy(Qt.CustomContextMenu)
        self.changes.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.changes, 1)
        self.hint = QLabel("双击打开文件，右键看差异/暂存")
        self.hint.setStyleSheet(_HINT_QSS + "padding:3px 8px;")
        v.addWidget(self.hint)

    def _commit_from_box(self):
        return self.commit(self.msg.text())

    def _git(self, args):
        try:
            return subprocess.run(
                ["git", "-c", "core.quotePath=false"] + list(args),
                cwd=self.root, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10)
        except Exception as e:  # 静默是故意的 - 没有 git 就显示不可用
            _x6_swallowed(__name__, e, "git command")
            return None

    def _git_ok(self, args):
        cp = self._git(args)
        if cp is None:
            return False, "没有 git 或不是仓库"
        if cp.returncode == 0:
            return True, (cp.stdout or "").strip()
        return False, (cp.stderr or cp.stdout or "").strip()

    def refresh(self, *_):
        self.changes.clear()
        cp = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = (cp.stdout or "").strip() if cp is not None else ""
        self.branch.setText("分支：%s" % (branch or "未检测到 Git 仓库"))
        entries = git_status_entries(self.root)
        if entries is None:
            self.hint.setText("当前目录不是 Git 仓库或未安装 git")
            return
        for status, rel in entries:
            item = QListWidgetItem("%s  %s" % (status, rel))
            item.setData(Qt.UserRole, os.path.join(self.root, rel))
            item.setData(Qt.UserRole + 1, rel)
            item.setData(Qt.UserRole + 2, status)
            color = _SCM_COLORS.get(status.strip()[:1], "#6e7781")
            item.setForeground(QBrush(QColor(color)))
            item.setToolTip("%s\n双击打开；右键可查看差异 / 暂存" % rel)
            self.changes.addItem(item)
        self.hint.setText("共 %d 个改动" % len(entries) if entries else "工作区干净")

    # ------------------------------------------------ 操作
    def _selected(self):
        item = self.changes.currentItem()
        if item is None:
            return None, ""
        return item, str(item.data(Qt.UserRole + 1) or "")

    def _status_of(self, rel):
        """按路径查状态：显式传 rel 时不能拿 currentItem 的状态凑数。"""
        for i in range(self.changes.count()):
            it = self.changes.item(i)
            if str(it.data(Qt.UserRole + 1) or "") == rel:
                return str(it.data(Qt.UserRole + 2) or "").strip()
        return ""

    def _menu(self, pos):
        item = self.changes.itemAt(pos)
        if item is None:
            return
        self.changes.setCurrentItem(item)
        rel = str(item.data(Qt.UserRole + 1) or "")
        menu = QMenu(self)
        menu.addAction("查看差异").triggered.connect(
            lambda *_: self.emit_diff(rel))
        menu.addAction("暂存").triggered.connect(lambda *_: self.stage(rel))
        menu.addAction("取消暂存").triggered.connect(
            lambda *_: self.unstage(rel))
        menu.addSeparator()
        menu.addAction("放弃改动…").triggered.connect(
            lambda *_: self.discard(rel))
        menu.exec_(self.changes.mapToGlobal(pos))

    def stage_all(self):
        ok, msg = self._git_ok(["add", "-A"])
        self.refresh()   # 先刷新，再写结果：refresh 会重置 hint
        self.hint.setText("已全部暂存" if ok else "暂存失败：%s" % msg[:120])
        return ok

    def stage(self, rel=None):
        if not rel:
            return self.stage_all()
        ok, msg = self._git_ok(["add", "--", rel])
        self.refresh()
        self.hint.setText("已暂存 %s" % rel if ok else "暂存失败：%s" % msg[:120])
        return ok

    def unstage(self, rel=None):
        if not rel:
            return False
        ok, msg = self._git_ok(["reset", "-q", "HEAD", "--", rel])
        if not ok:   # 还没有任何提交时 reset 会失败，退回 rm --cached
            ok, msg = self._git_ok(["rm", "--cached", "-q", "--", rel])
        self.refresh()
        self.hint.setText("已取消暂存 %s" % rel if ok else "取消失败：%s" % msg[:120])
        return ok

    def discard(self, rel=None):
        _, sel = self._selected()
        rel = rel or sel
        if not rel:
            return False
        status = self._status_of(rel)
        if QMessageBox.question(
                self, "放弃改动",
                "确定丢弃 %s 的改动？此操作不可恢复。" % rel,
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        path = os.path.join(self.root, rel)
        if status.strip().startswith("?"):
            if not os.path.isfile(path):
                self.hint.setText("目录改动请手动处理：%s" % rel)
                return False
            try:
                os.remove(path)
                ok, msg = True, ""
            except OSError as e:
                ok, msg = False, str(e)
        elif "A" in status:
            # 新加入暂存区的文件在 HEAD 里不存在，"退回提交状态"就是删掉它
            ok, msg = self._git_ok(["rm", "-q", "-f", "--cached", "--", rel])
            if ok:
                try:
                    os.remove(path)
                except OSError as e:
                    ok, msg = False, str(e)
        else:
            # `checkout -- rel` 只从索引恢复：已暂存的改动会原地留着，
            # 看起来像"放弃无效"。这里连暂存区一起退回 HEAD。
            ok, msg = self._git_ok(["checkout", "HEAD", "--", rel])
        self.refresh()
        self.hint.setText("已放弃 %s" % rel if ok else "放弃失败：%s" % msg[:120])
        return ok

    def commit(self, message=None):
        msg = str(self.msg.text() if message is None else message).strip()
        if not msg:
            self.hint.setText("先填提交信息再提交")
            self.msg.setFocus()
            return False
        cp = self._git(["diff", "--cached", "--quiet"])
        if cp is None:
            self.hint.setText("没有 git 或不是仓库")
            return False
        if cp.returncode == 0:
            self.hint.setText("暂存区是空的：先暂存要提交的文件")
            return False
        ok, out = self._git_ok(["commit", "-m", msg])
        if not ok:
            self.hint.setText("提交失败：%s" % (out or "未知错误")[:120])
            return False
        sha_cp = self._git(["rev-parse", "--short", "HEAD"])
        sha = (sha_cp.stdout or "").strip() if sha_cp is not None else ""
        self.msg.clear()
        self.refresh()
        self.hint.setText("已提交 %s" % (sha or "OK"))
        self.commitDone.emit(sha)
        return True

    def emit_diff(self, rel=None):
        if not rel:
            _, rel = self._selected()
        if not rel:
            return ""
        status = self._status_of(rel)
        cp = self._git(["diff", "--cached", "--", rel])
        text = (cp.stdout or "") if cp is not None else ""
        if not text.strip():
            cp = self._git(["diff", "--", rel])
            text = (cp.stdout or "") if cp is not None else ""
        if not text.strip() and status.strip().startswith("?"):
            text = "（未跟踪的新文件：暂存后才有差异）"
        self.diffRequested.emit(rel, text)
        return text

    def _open_item(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(str(path)):
            self.openRequested.emit(str(path))
