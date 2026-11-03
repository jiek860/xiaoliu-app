# -*- coding: utf-8 -*-
"""工作台工作区（root）：选目录、记住上次、切换时同步各面板。

为什么单独成模块
----------------
``gui/workbench_dialog.py`` 受 ``tests/test_module_split_exports.py`` 的
≤500 行约束，而"写代码写到哪个文件夹"这件事与布局无关，放这里能单测。

历史问题（用户实测反馈）
------------------------
以前 ``WorkbenchWindow.__init__`` 把 root 写死成 ``trunk.base``：

* 也就是**程序自己所在的目录**，用户让它"写一个时钟软件"，
  ``clock.py`` 会被塞进 ``gui/`` ``core/`` 旁边，和程序源码混在一起；
* 界面上没有任何"选写到哪个文件夹"的入口（老窗口 ``code_agent_dialog``
  反而有「选择项目目录」，合并成工作台时漏掉了）。

现在：可选目录 + 记住上次（``config.json`` 的 ``workbench_root``）+
默认是程序目录时给出提示。
"""
from __future__ import annotations

import os

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None

CFG_KEY = "workbench_root"


def program_root(trunk):
    """程序自身目录 —— 没选工作区时的默认 root。"""
    try:
        return os.path.abspath(str(getattr(trunk, "base", "") or os.getcwd()))
    except OSError as e:
        _x6_swallowed(__name__, e, "program root")
        return os.getcwd()


def remembered_root(trunk):
    """上次选过的工作区；目录已经不在就返回空（别把用户钉在已删除的路径上）。"""
    try:
        cfg = getattr(trunk, "config", None) or {}
        path = str(cfg.get(CFG_KEY) or "").strip() if isinstance(cfg, dict) else ""
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    except Exception as e:  # 静默是故意的 - 读不到就当没记过
        _x6_swallowed(__name__, e, "read workbench root")
    return ""


def resolve_root(trunk):
    """工作台启动时的 root：上次选的优先，否则程序目录。"""
    return remembered_root(trunk) or program_root(trunk)


def remember_root(trunk, path):
    """把用户选的目录写进 config.json（下次打开工作台直接用它）。"""
    path = os.path.abspath(str(path))
    try:
        cfg = getattr(trunk, "config", None)
        if isinstance(cfg, dict):
            cfg[CFG_KEY] = path
        save = getattr(trunk, "save_config", None)
        if callable(save):
            save()
    except Exception as e:  # 静默是故意的 - 存不下也不影响本次使用
        _x6_swallowed(__name__, e, "save workbench root")
    return path


def is_program_dir(trunk, root):
    """当前 root 是不是"程序自己的目录"（写进去会污染程序源码）。"""
    try:
        return os.path.abspath(str(root or "")) == program_root(trunk)
    except Exception as e:  # 静默是故意的 - 比不出来就当不是
        _x6_swallowed(__name__, e, "compare workbench root")
        return False


def root_hint(trunk, root):
    """默认目录是程序目录时返回一句提醒，否则返回空字符串。"""
    if not is_program_dir(trunk, root):
        return ""
    return ("⚠ 当前工作区是程序目录（%s）：AI 写的文件会和程序源码混在一起。"
            "点右上「📂 打开文件夹」选一个项目文件夹再写代码。"
            % os.path.basename(str(root)))


_TRANSLATOR = None


def install_chinese_translator():
    """给 Qt 自带对话框装中文翻译（``qt_zh_CN.qm``）。

    为什么要这一步：目录框用的是 Qt 自己的界面（``DontUseNativeDialog``），
    不装翻译就是 Look in / Name / Size / Choose / Cancel / All Files (*)
    这一屏英文；装了才是「查找范围 / 名称 / 大小 / 选择 / 取消 / 所有文件」。
    翻译器必须留模块级引用，否则被 Python 回收后翻译立刻失效。
    """
    global _TRANSLATOR
    if _TRANSLATOR is not None:
        return _TRANSLATOR
    try:
        from PyQt5.QtCore import QLibraryInfo, QTranslator
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return None
        path = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
        tr = QTranslator(app)
        for name in ("qt_zh_CN", "qt_zh_TW"):
            if tr.load(name, path):
                app.installTranslator(tr)
                _TRANSLATOR = tr
                return tr
    except Exception as e:  # 静默是故意的 - 没有翻译文件就保持英文，不影响选目录
        _x6_swallowed(__name__, e, "install qt translator")
    return _TRANSLATOR


def desktop_dir():
    """当前用户的桌面目录（取不到返回空字符串）。

    目录选择框在 ``gui/folder_picker.py``；这里保留同名入口，供启动默认路径使用。
    """
    from gui.folder_picker import desktop_dir as _impl
    return _impl()


def choose_folder(parent, current=""):
    """弹中文目录选择框；取消返回空字符串。

    为什么不用 ``QFileDialog.getExistingDirectory``
    --------------------------------------------
    ① 默认会调系统原生对话框：个别环境（远程桌面、精简系统、主题接管）原生框
       不出现或一闪而过，用户点了「📂 打开文件夹」像是"没反应/改不了"；
    ② Qt 自带对话框（``DontUseNativeDialog``）的按钮/表头是英文，左侧快捷位置
       显示的又是文件夹真实名字（Desktop / 用户名 / 盘符），装语言包也改不掉
       （QUrlModel 没有改名接口，实测包一层代理模型会让点击失效）。
    所以这里用 ``gui/folder_picker.FolderPicker``：全中文、左侧有「桌面」。
    """
    install_chinese_translator()
    start = str(current or "")
    if not os.path.isdir(start):
        start = desktop_dir() or os.path.expanduser("~")
    try:
        from PyQt5.QtWidgets import QDialog
        from gui.folder_picker import FolderPicker
        dlg = FolderPicker(parent, start)
        if dlg.exec_() != QDialog.Accepted:
            return ""
        picked = dlg.selected_path()
        return picked if picked and os.path.isdir(picked) else ""
    except Exception as e:  # 静默是故意的 - 目录框起不来就改手输
        _x6_swallowed(__name__, e, "choose folder dialog")
        return type_folder_path(parent, start)


def type_folder_path(parent, start=""):
    """兜底：直接输入目录完整路径（目录框打不开时用）。

    输入框用 ``gui.folder_picker.ask_text``：静态 ``QInputDialog.getText``
    的按钮走系统主题，装了 qt_zh_CN 也是 OK/Cancel（实测）。
    """
    try:
        from gui.folder_picker import ask_text
        text = ask_text(parent, "输入工作区文件夹",
                        "文件夹完整路径（例如 D:\\我的项目）：",
                        str(start or ""))
        if not text:
            return ""
        path = os.path.abspath(str(text).strip('"'))
        return path if os.path.isdir(path) else ""
    except Exception as e:  # 静默是故意的 - 兜底也失败就当取消
        _x6_swallowed(__name__, e, "type folder path")
        return ""


def tell(wb, text, timeline=False):
    """把工作区相关结果回显到状态栏（timeline=True 时同时写 AI 时间线）。

    用户点了链接却什么都没变，就会以为"这个改不了"——所以每个出口都要有字。
    """
    text = str(text or "")
    if not text:
        return
    try:
        wb.status_label.setText(text)
        wb.status_label.setToolTip(text)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "status workspace message")
    if not timeline:
        return
    try:
        if getattr(wb, "ai_dock", None) is not None:
            wb.ai_dock.timeline.appendPlainText(text)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "timeline workspace message")


def repoint_editor(editor, path):
    """把编辑器的文件树 / 输出面板指到新 root（已打开的标签页保留）。"""
    if editor is None:
        return
    try:
        editor.root = path
        editor.fs_model.setRootPath(path)
        editor.tree.setRootIndex(editor.fs_model.index(path))
        if hasattr(editor, "refresh_git_marks"):
            editor.refresh_git_marks()
        bottom = getattr(editor, "bottom", None)
        if bottom is not None and hasattr(bottom, "root"):
            bottom.root = path
    except Exception as e:  # 静默是故意的 - 文件树换根失败也不该崩
        _x6_swallowed(__name__, e, "repoint editor root")


def apply_root(wb, path, remember=True):
    """把工作台切到新工作区：文件树 / 搜索 / Git / AI 队列一起换。

    只改"看哪里、写哪里"，**不重建窗口** —— 已经打开的编辑器标签保留，
    用户正在手改的内容不会因为换工作区消失。

    返回 ``{"ok": bool, "root": 新路径, "previous": 旧路径, "error": 说明}``。
    """
    path = os.path.abspath(str(path or ""))
    if not os.path.isdir(path):
        return {"ok": False, "error": "目录不存在: " + path}
    previous = str(getattr(wb, "root", "") or "")
    wb.root = path

    try:
        wb.root_label.setText(os.path.basename(path) or path)
        wb.root_label.setToolTip(path)
    except Exception as e:  # 静默是故意的 - 标签不存在也不影响切换
        _x6_swallowed(__name__, e, "update root label")
    try:
        from gui.ide_sidebar import git_branch
        wb.branch_label.setText("⎇ %s" % git_branch(path))
    except Exception as e:  # 静默是故意的 - 非 git 目录显示 "-" 即可
        _x6_swallowed(__name__, e, "update branch label")

    editor = getattr(wb, "_editor", None)
    repoint_editor(editor, path)

    host = getattr(wb, "sidebar_stack", None)
    if host is not None:
        for view in (getattr(host, "search_view", None),
                     getattr(host, "scm_view", None)):
            if view is not None and hasattr(view, "root"):
                view.root = path
        try:
            if getattr(host, "search_view", None) is not None:
                host.search_view._clear()
            if getattr(host, "scm_view", None) is not None:
                host.scm_view.refresh()
        except Exception as e:  # 静默是故意的 - 视图刷新失败不影响自身
            _x6_swallowed(__name__, e, "refresh sidebar views")

    dock = getattr(wb, "ai_dock", None)
    if dock is not None:
        # 队列/服务按 root 建（core.agent_service.get_agent_service 按 root 复用），
        # 换目录后必须丢旧引用，下一次"开始"才会用新目录。
        # 但任务正在跑时不能丢：后台线程的审批应答还要用 service，
        # 丢了会让审批超时按拒绝处理（fail-closed），任务莫名失败。
        running = bool(getattr(dock, "_running", False))
        if running:
            try:
                dock.timeline.appendPlainText(
                    "⚠ 上一个任务仍在旧工作区（%s）里跑，等它结束再开始新任务"
                    % (os.path.basename(previous) or previous))
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "append running warning")
        else:
            for name, value in (("queue", None), ("service", None),
                                ("current_job_id", "")):
                try:
                    setattr(dock, name, value)
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "reset ai dock state")
            try:
                dock.timeline.appendPlainText("📂 工作区已切到: " + path)
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "append workspace switch")

    if remember:
        remember_root(getattr(wb, "trunk", None), path)
    return {"ok": True, "root": path, "previous": previous}


def open_folder_picker(wb):
    """「📂 打开文件夹」的行为：选目录 → 切换 → 回显提示。

    每个出口都要有回显：取消 / 没变化 / 失败 / 成功，否则用户点了链接
    屏幕上什么都不变，就会以为"这个改不了"。
    """
    current = getattr(wb, "root", "") or program_root(getattr(wb, "trunk", None))
    path = choose_folder(wb, current)
    if not path:
        tell(wb, "已取消选择：工作区仍是 " + (os.path.basename(current)
                                             or str(current)), timeline=True)
        return {"ok": False, "cancelled": True}
    if path == os.path.abspath(str(current or "")):
        tell(wb, "工作区没有变化：" + (os.path.basename(path) or path),
             timeline=True)
        return {"ok": True, "root": path, "unchanged": True}
    result = apply_root(wb, path)
    if not result.get("ok"):
        tell(wb, "⚠ 切换工作区失败：" + str(result.get("error") or "目录不可用")
             + "（仍在使用 " + (os.path.basename(current) or str(current)) + "）",
             timeline=True)
        return result
    tell(wb, "工作区: " + (os.path.basename(path) or path))
    return result


def show_root_hint(wb):
    """启动时回显：默认工作区是程序目录就提示一句（不弹框，不挡操作）。"""
    trunk = getattr(wb, "trunk", None)
    root = getattr(wb, "root", "") or program_root(trunk)
    text = root_hint(trunk, root)
    if not text:
        return ""
    tell(wb, text, timeline=True)
    return text
