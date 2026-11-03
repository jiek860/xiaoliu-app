# -*- coding: utf-8 -*-
"""中文目录选择框：替代 QFileDialog 的一屏英文。

为什么要自己写
--------------
Qt 自带目录框（``DontUseNativeDialog``）的文字来自语言包：不装 qt_zh_CN 就是
Look in / Name / Size / Choose / Cancel / All Files (*)；装了之后按钮变中文，
但左侧快捷位置显示的是文件夹**真实名字**（Desktop、用户名、盘符），用户还是
会觉得"怎么全是英文"。而 QUrlModel 没有提供改名接口（实测代理模型会让点击
失效），所以这里用标准控件拼一个：

    位置栏（可粘贴完整路径） + 快捷位置（桌面 / 用户文件夹 / 各磁盘）
    + 目录树 + ＋新建文件夹 / 选择 / 取消

选目录本来就是"必须弹框让用户指"的操作，所以这里用 QDialogButtonBox 的
确认/取消，不额外往全局按钮预算里加散按钮。
"""
from __future__ import annotations

import os

from PyQt5.QtCore import QDir, Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFileSystemModel,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QTreeView, QVBoxLayout)

from gui.feedback_states import make_action_links

try:
    from core.logger import swallow as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(*_a, **_k):
        return None


def desktop_dir():
    """当前用户的桌面目录（取不到返回空字符串）。"""
    try:
        from PyQt5.QtCore import QStandardPaths
        path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    except Exception as e:  # 静默是故意的 - 没桌面目录就少一个快捷位置
        _x6_swallowed(__name__, e, "desktop dir")
    return ""


def home_dir():
    """用户文件夹（文档、下载一般都在它下面）。"""
    try:
        path = QDir.homePath()
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "home dir")
    return ""


def _standard_dir(kind):
    try:
        from PyQt5.QtCore import QStandardPaths
        path = QStandardPaths.writableLocation(kind)
        if path and os.path.isdir(path):
            return os.path.abspath(path)
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "standard dir")
    return ""


def _has_han(text):
    """是否含中文（卷标通常是中文，取不到时退回"磁盘 (C:)"）。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _drives():
    """[(显示名, 路径)]：本地磁盘、U 盘等。显示名优先用系统卷标。"""
    out = []
    try:
        from PyQt5.QtCore import QStorageInfo
        for info in QStorageInfo.mountedVolumes():
            path = info.rootPath()
            if not path or not os.path.isdir(path):
                continue
            drive = os.path.splitdrive(path)[0] or path
            name = str(info.displayName() or "").strip()
            # QStorageInfo.displayName() 在没卷标时直接返回 "C:/"，不是给人看的
            if not _has_han(name) or name.rstrip("/\\") in (path.rstrip("/\\"),
                                                            drive):
                name = "磁盘 (%s)" % drive
            out.append((name, os.path.abspath(path)))
    except Exception as e:  # 静默是故意的 - 取不到就退回 QDir.drives()
        _x6_swallowed(__name__, e, "mounted volumes")
    if not out:
        try:
            for info in QDir.drives():
                path = info.absolutePath()
                if os.path.isdir(path):
                    out.append(("磁盘 (%s)" % os.path.splitdrive(path)[0],
                                os.path.abspath(path)))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "drives")
    return out


def quick_places():
    """左侧快捷位置：[(显示名, 路径)] —— 桌面排第一，方便"项目就在桌面上"。"""
    out = []
    for label, path in (("🖥 桌面", desktop_dir()),
                        ("🏠 用户文件夹", home_dir()),
                        ("📄 文档",
                         _standard_dir("DocumentsLocation")),
                        ("📥 下载",
                         _standard_dir("DownloadLocation"))):
        if path and not any(path == p for _l, p in out):
            out.append((label, path))
    for label, path in _drives():
        if not any(path == p for _l, p in out):
            out.append(("💽 " + label, path))
    return out


def ensure_chinese_ui():
    """让 Qt 自带的小弹窗（「新建文件夹」里的确定/取消）也显示中文。"""
    try:
        from gui.workbench_workspace import install_chinese_translator
        return install_chinese_translator()
    except Exception as e:  # 静默是故意的 - 没翻译只影响 Qt 自带小弹窗
        _x6_swallowed(__name__, e, "install qt translator")
    return None


def text_dialog(parent=None, title="", label="", default="",
                ok_text="确定", cancel_text="取消"):
    """构造按钮为中文的输入框。

    为什么不用静态 ``QInputDialog.getText``：它的确定/取消走
    ``QPlatformTheme`` 的标准按钮文字，装了 qt_zh_CN 依然是 OK/Cancel。
    """
    from PyQt5.QtWidgets import QInputDialog
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(str(default or ""))
    dlg.setOkButtonText(ok_text)
    dlg.setCancelButtonText(cancel_text)
    return dlg


def ask_text(parent=None, title="", label="", default=""):
    """弹中文输入框，返回输入的文字；点取消返回空字符串。"""
    try:
        from PyQt5.QtWidgets import QDialog
        dlg = text_dialog(parent, title, label, default)
        if dlg.exec_() != QDialog.Accepted:
            return ""
        return str(dlg.textValue() or "").strip()
    except Exception as e:  # 静默是故意的 - 输入框起不来就当取消
        _x6_swallowed(__name__, e, "ask text")
        return ""


class FolderPicker(QDialog):
    """选一个文件夹：全中文，左侧带「桌面」等快捷位置。"""

    def __init__(self, parent=None, start="", title="选择工作区文件夹"):
        super().__init__(parent)
        ensure_chinese_ui()
        self.setWindowTitle(title)
        self.resize(860, 560)
        self._current = self._first_existing(start)
        self._selected = ""
        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.model.setRootPath(QDir.rootPath())
        self.model.sort(0, Qt.AscendingOrder)
        self._build()
        self.set_path(self._current)

    @staticmethod
    def _first_existing(*candidates):
        for path in candidates:
            text = str(path or "")
            if text and os.path.isdir(text):
                return os.path.abspath(text)
        return os.path.abspath(home_dir() or QDir.rootPath())

    # ------------------------------------------------------ 构建
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("位置："))
        self.path_edit = QLineEdit()
        self.path_edit.setToolTip("可以直接粘贴一个完整路径，回车跳转")
        self.path_edit.returnPressed.connect(self._on_typed)
        top.addWidget(self.path_edit, 1)
        top.addWidget(make_action_links([("上一级", self._go_up)]))
        v.addLayout(top)

        mid = QHBoxLayout()
        self.places = QListWidget()
        self.places.setFixedWidth(190)
        self.places.setToolTip("快捷位置：桌面 / 用户文件夹 / 各磁盘")
        self.places.itemClicked.connect(self._on_place)
        mid.addWidget(self.places)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderHidden(True)
        self.tree.setAlternatingRowColors(True)
        for col in (1, 2, 3):          # 只有"名称"一列就够选文件夹
            self.tree.setColumnHidden(col, True)
        self.tree.clicked.connect(self._on_item_clicked)
        self.tree.doubleClicked.connect(self._on_item_activated)
        mid.addWidget(self.tree, 1)
        v.addLayout(mid, 1)

        foot = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#475467;font-size:12px;")
        foot.addWidget(self.hint, 1)
        foot.addWidget(make_action_links([("＋ 新建文件夹", self._new_folder)]))
        self.box = QDialogButtonBox(self)
        self.ok_btn = self.box.addButton("选择", QDialogButtonBox.AcceptRole)
        self.cancel_btn = self.box.addButton("取消",
                                             QDialogButtonBox.RejectRole)
        self.ok_btn.setToolTip("把当前选中的文件夹作为工作区")
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        foot.addWidget(self.box)
        v.addLayout(foot)

        self._fill_places()

    def _fill_places(self):
        self.places.clear()
        for label, path in quick_places():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.places.addItem(item)

    # ------------------------------------------------------ 导航
    def current_path(self):
        """当前所在的文件夹（目录树里显示的内容就是它的子项）。"""
        return self._current

    def selected_path(self):
        """用户选中的文件夹；没点具体文件夹时用当前所在目录。"""
        return self._selected or self._current

    def set_path(self, path):
        """把目录树切到 ``path``（显示它下面的子文件夹）。"""
        text = str(path or "").strip().strip('"')
        if not (text and os.path.isdir(text)):
            self.hint.setText("目录不存在：" + (text or "（空）"))
            return False
        self._current = os.path.abspath(text)
        self._selected = ""
        self.path_edit.setText(self._current)
        self.tree.setRootIndex(self.model.index(self._current))
        self.hint.setText("当前：" + self._current)
        return True

    def _on_typed(self):
        if not self.set_path(self.path_edit.text()):
            self.path_edit.setText(self._current)

    def _go_up(self):
        parent = os.path.dirname(self._current.rstrip("\\/")) or QDir.rootPath()
        self.set_path(parent)

    def _on_place(self, item):
        self.set_path(str(item.data(Qt.UserRole) or ""))

    def _on_item_clicked(self, index):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self._selected = os.path.abspath(path)
            self.hint.setText("已选择：" + self._selected)

    def _on_item_activated(self, index):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.set_path(path)

    def _name_dialog(self):
        """「新建文件夹」输入框：按钮用中文。"""
        return text_dialog(self, "新建文件夹", "文件夹名称：")

    def _ask_folder_name(self):
        """弹「新建文件夹」输入框，返回名字；取消或为空返回空字符串。"""
        return ask_text(self, "新建文件夹", "文件夹名称：")

    def _new_folder(self):
        name = self._ask_folder_name()
        if not name:
            return
        try:
            path = os.path.join(self._current, name)
            os.makedirs(path, exist_ok=True)
        except Exception as e:  # 静默是故意的 - 建不出来就提示用户
            _x6_swallowed(__name__, e, "create folder")
            self.hint.setText("新建文件夹失败：" + str(e)[:60])
            return
        self.set_path(path)

    # ------------------------------------------------------ 确认
    def accept(self):
        if not os.path.isdir(self.selected_path()):
            self.hint.setText("请先选中一个文件夹")
            return
        super().accept()
