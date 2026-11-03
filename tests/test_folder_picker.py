# -*- coding: utf-8 -*-
"""中文目录选择框：左侧要有「桌面」，界面文字不能是英文。"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt5.QtWidgets")
from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

from gui import folder_picker as fp  # noqa: E402

_HAN = re.compile(r"[\u4e00-\u9fff]")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_quick_places_desktop_first():
    places = fp.quick_places()
    assert places, "快捷位置不能为空"
    labels = [label for label, _path in places]
    assert any("桌面" in label for label in labels), labels
    desktop = fp.desktop_dir()
    if desktop:
        assert places[0][1] == desktop, "桌面应排第一"


def test_quick_places_are_chinese():
    for label, path in fp.quick_places():
        assert _HAN.search(label), "快捷位置名要含中文：%s" % label
        assert os.path.isdir(path), path


def test_dialog_texts_are_chinese(app, tmp_path):
    dlg = fp.FolderPicker(None, str(tmp_path))
    dlg.show()
    app.processEvents()
    assert dlg.ok_btn.text() == "选择"
    assert dlg.cancel_btn.text() == "取消"
    assert dlg.windowTitle() == "选择工作区文件夹"
    assert dlg.tree.isHeaderHidden() is True, "不显示 Name/Size 这类英文表头"
    for col in (1, 2, 3):
        assert dlg.tree.isColumnHidden(col) is True
    dlg.close()


def test_set_path_and_selected_path(app, tmp_path):
    dlg = fp.FolderPicker(None, str(tmp_path))
    assert dlg.current_path() == os.path.abspath(str(tmp_path))
    assert dlg.selected_path() == os.path.abspath(str(tmp_path))
    assert dlg.path_edit.text() == os.path.abspath(str(tmp_path))
    dlg.close()


def test_set_path_rejects_missing_dir(app, tmp_path):
    dlg = fp.FolderPicker(None, str(tmp_path))
    old = dlg.current_path()
    missing = str(tmp_path / "没有这个目录")
    assert dlg.set_path(missing) is False
    assert dlg.current_path() == old
    assert "目录不存在" in dlg.hint.text()
    dlg.close()


def test_clicking_sub_folder_selects_it(app, tmp_path):
    sub = tmp_path / "子项目"
    sub.mkdir()
    dlg = fp.FolderPicker(None, str(tmp_path))
    dlg.show()
    app.processEvents()
    idx = dlg.model.index(str(sub))
    assert idx.isValid(), "目录树里应能找到子文件夹"
    dlg._on_item_clicked(idx)
    assert dlg.selected_path() == os.path.abspath(str(sub))
    assert "已选择" in dlg.hint.text()
    dlg.close()


def test_double_click_enters_folder(app, tmp_path):
    sub = tmp_path / "子项目"
    sub.mkdir()
    dlg = fp.FolderPicker(None, str(tmp_path))
    dlg.show()
    app.processEvents()
    idx = dlg.model.index(str(sub))
    dlg._on_item_activated(idx)
    assert dlg.current_path() == os.path.abspath(str(sub))
    assert dlg.selected_path() == os.path.abspath(str(sub))
    dlg.close()


def test_accept_needs_existing_dir(app, tmp_path):
    dlg = fp.FolderPicker(None, str(tmp_path))
    caught = []
    dlg.accepted.connect(lambda: caught.append(1))
    dlg.set_path(str(tmp_path))
    dlg.accept()
    assert caught, "有有效目录时应能确认关闭"


def test_new_folder_creates_and_enters(app, tmp_path, monkeypatch):
    monkeypatch.setattr(fp.FolderPicker, "_ask_folder_name",
                        lambda self: "新项目")
    dlg = fp.FolderPicker(None, str(tmp_path))
    dlg._new_folder()
    created = tmp_path / "新项目"
    assert created.is_dir()
    assert dlg.current_path() == os.path.abspath(str(created))
    dlg.close()


def test_new_folder_cancel_does_nothing(app, tmp_path, monkeypatch):
    monkeypatch.setattr(fp.FolderPicker, "_ask_folder_name", lambda self: "")
    dlg = fp.FolderPicker(None, str(tmp_path))
    dlg._new_folder()
    assert [p.name for p in tmp_path.iterdir()] == []
    dlg.close()


def test_new_folder_dialog_is_chinese(app, tmp_path):
    """「新建文件夹」输入框的确定/取消也必须是中文（不能是 OK/Cancel）。"""
    dlg = fp.FolderPicker(None, str(tmp_path))
    ask = dlg._name_dialog()
    assert ask.windowTitle() == "新建文件夹"
    assert ask.okButtonText() == "确定", ask.okButtonText()
    assert ask.cancelButtonText() == "取消", ask.cancelButtonText()
    ask.close()
    dlg.close()


def test_text_dialog_is_chinese(app):
    """共用输入框（手输路径那种）的按钮也必须是中文。"""
    d = fp.text_dialog(None, "输入工作区文件夹", "文件夹完整路径：")
    assert d.windowTitle() == "输入工作区文件夹"
    assert d.okButtonText() == "确定", d.okButtonText()
    assert d.cancelButtonText() == "取消", d.cancelButtonText()
    d.close()


def test_ask_text_returns_trimmed_value(app, monkeypatch):
    class _Fake:
        def exec_(self):
            return QDialog.Accepted

        def textValue(self):
            return "  abc  "

    monkeypatch.setattr(fp, "text_dialog", lambda *_a, **_k: _Fake())
    assert fp.ask_text(None, "t", "l") == "abc"


def test_ask_text_cancel_returns_empty(app, monkeypatch):
    class _Fake:
        def exec_(self):
            return QDialog.Rejected

        def textValue(self):
            return "abc"

    monkeypatch.setattr(fp, "text_dialog", lambda *_a, **_k: _Fake())
    assert fp.ask_text(None, "t", "l") == ""


def test_choose_folder_uses_picker(tmp_path, monkeypatch):
    """工作区的「📂 打开文件夹」走的是这个中文框。"""
    from gui import workbench_workspace as ww
    calls = {}

    class _FakePicker:
        def __init__(self, parent=None, start="", title="选择工作区文件夹"):
            calls["start"] = start
            calls["title"] = title
            self._path = str(tmp_path)

        def exec_(self):
            return QDialog.Accepted

        def selected_path(self):
            return self._path

    monkeypatch.setattr(fp, "FolderPicker", _FakePicker)
    assert ww.choose_folder(None, str(tmp_path)) == os.path.abspath(str(tmp_path))
    assert calls["title"] == "选择工作区文件夹"
