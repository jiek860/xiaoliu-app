# -*- coding: utf-8 -*-
"""标签页右键菜单（M1 拆分）：从 599 行的 ``code_editor_dialog`` 里挪出来。

内容包括：保存、推送 PR、复制路径、在文件树定位、关闭标签页。
拆分的直接原因：主文件已顶到 600 行上限，任何新增都要先腾位置。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox


def install(dialog):
    """给标签栏装上右键菜单（QAction 不占按钮预算中的按钮数）。"""
    dialog.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
    dialog.tabs.customContextMenuRequested.connect(
        lambda pos: show_menu(dialog, pos))


def show_menu(dialog, pos):
    w = dialog._current_edit()
    if w is None:
        return
    menu = QMenu(dialog)
    if getattr(w, "filepath", ""):
        act_save = menu.addAction("保存")
        act_save.triggered.connect(lambda: dialog._save_w(w))
        act_pr = menu.addAction("推送到 GitHub 并创建 PR")
        act_pr.triggered.connect(lambda: push_pr(dialog))
        menu.addSeparator()
        act_copy = menu.addAction("复制路径")
        act_copy.triggered.connect(lambda: copy_path(dialog, w))
        act_reveal = menu.addAction("在文件树中定位")
        act_reveal.triggered.connect(lambda: reveal_in_tree(dialog, w))
        act_ai = menu.addAction("发送到 AI（含选区）")
        act_ai.triggered.connect(lambda: send_context_to_ai(dialog))
        menu.addSeparator()
    act_sig = menu.addAction("插入函数调用模板")
    act_sig.triggered.connect(lambda: insert_signature(dialog, w))
    act_close = menu.addAction("关闭标签页")
    act_close.triggered.connect(
        lambda: dialog._close_tab(dialog.tabs.currentIndex()))
    menu.exec_(dialog.tabs.mapToGlobal(pos))


def copy_path(dialog, w):
    path = getattr(w, "filepath", "") or ""
    if path:
        QApplication.clipboard().setText(path)
        dialog._status("已复制路径", 3000)


def reveal_in_tree(dialog, w):
    path = getattr(w, "filepath", "") or ""
    if not path:
        return
    try:
        dialog.tree.setCurrentIndex(dialog.fs_model.index(path))
        dialog.tree.scrollTo(dialog.fs_model.index(path))
        dialog._status("已在文件树中定位", 3000)
    except Exception as e:
        _x6_swallowed(__name__, e, "reveal in tree")


def send_context_to_ai(dialog):
    """「发送到 AI」：把当前文件/选区放进工作台 AI 目标框。"""
    try:
        from gui.workbench_context import send_to_ai
        send_to_ai(dialog)
    except Exception as e:
        _x6_swallowed(__name__, e, "send tab context to ai")


def insert_signature(dialog, w):
    """光标所在函数 -> 插入 ``foo(a=a, b=b)`` 调用模板。"""
    try:
        from core.code import signature
        text = w.toPlainText()
        line = w.textCursor().blockNumber() + 1
        sig = signature.signature_at(text, line)
        if not sig:
            dialog._status("光标不在函数体内，无法生成调用模板", 3000)
            return ""
        tpl = signature.call_template(sig)
        cur = w.textCursor()
        cur.insertText(tpl)
        w.setTextCursor(cur)
        dialog._status("已插入调用模板: " + tpl, 4000)
        return tpl
    except Exception as e:
        _x6_swallowed(__name__, e, "insert signature template")
        return ""


def push_pr(dialog):
    """把当前文件提交到功能分支并创建 PR（走 api.github.com）。"""
    w = dialog._current_edit()
    path = getattr(w, "filepath", "") if w else ""
    if not path:
        QMessageBox.information(dialog, "PR", "请先保存文件")
        return
    root = os.path.abspath(getattr(dialog.trunk, "base", ".") or ".")
    rel = os.path.relpath(path, root).replace("\\", "/")
    try:
        from core.github_pr import PRFlow
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = PRFlow(dialog.trunk, root).run(
                [(rel, w.toPlainText())],
                title="chore: 更新 %s" % os.path.basename(path),
                body="由小6代码编辑器发起", wait_ci=False)
        finally:
            QApplication.restoreOverrideCursor()
        if r.get("ok"):
            QMessageBox.information(
                dialog, "已创建 PR",
                "%s\n%s" % ((r.get("pr") or {}).get("url", ""),
                            "分支: " + str(r.get("branch"))))
        else:
            QMessageBox.warning(dialog, "PR 失败", str(r.get("error"))[:500])
    except Exception as e:
        QMessageBox.warning(dialog, "PR 失败", str(e)[:500])
