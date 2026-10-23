# -*- coding: utf-8 -*-
"""设置窗口的入口按钮必须真的能打开东西

为什么单独写这个文件
--------------------
实测踩到过（2026-10-13，用户截图发现的）：设置里
「⚙️ 系统」「🧩 插件」「📋 日志」「🔌 MCP」四个按钮**全部点不动**。
根因是 gui/mixins/dialog_mixin.py 的 _panel_commands 把查表的键名
改得更清楚了（"系统"→"系统自检"、"插件"→"插件市场"、
"日志"→"日志中心"、"MCP"→"MCP市场"），
而设置窗口是**按名字查表**的 —— 对不上就 setEnabled(False) 静默置灰。

**为什么现有测试都没抓到**：
    · _open_btn 是**优雅降级**的（置灰 + tooltip），不抛异常
    · test_gui_smoke 只验"对话框能构造、有子控件"—— 置灰的按钮照样算数
    · test_ui_responsiveness 直接调 win.sys_dialog()，**绕过了设置里那个按钮**
    · 界面上没有任何报错，也没有日志

所以这一类"按钮在、但已经死了"的坏法，必须专门验。

⚠️ 主窗口**一个进程里只建一次**：
   第一版我在两个用例里各建了一个 JarvisWindow，跑起来直接崩
   （退出码 0xC0000409 栈溢出，不是 Python 异常，pytest 连报错都打不出来）。
   改成模块级 fixture 共用一个。
"""
import os
import re
import sys
import unittest.mock as mock

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SETTINGS = os.path.join(BASE, "gui", "settings_dialog.py")

# ⚠️ 必须先有 QApplication 才能建任何 QWidget。
#    第一版漏了这句，三个用到主窗口的用例全部硬崩
#    （退出码 0xC0000409，连 pytest 的报错都打不出来，只留一个"."）。
#    test_gui_smoke.py 也是在模块顶层建的，照做。
from PyQt5.QtWidgets import QApplication          # noqa: E402
_app = QApplication.instance() or QApplication(sys.argv)

_win = None


@pytest.fixture(scope="module")
def win():
    """整个模块共用一个主窗口（建第二个会崩）"""
    global _win
    if _win is None:
        from core.trunk import Trunk
        from tests.conftest import _BACKGROUND
        patchers = [mock.patch.object(Trunk, n, lambda self: None)
                    for n in _BACKGROUND]
        for p in patchers:
            p.start()
        try:
            from gui.main_window import JarvisWindow
            _win = JarvisWindow()
        finally:
            for p in patchers:
                p.stop()
    return _win


def _open_btn_calls():
    """解析设置窗口里每一处 _open_btn(...) 的 (显示名, key)

    key 不传时就是显示名（见 _open_btn 的说明）。
    """
    src = open(SETTINGS, encoding="utf-8").read()
    out = []
    for m in re.finditer(r'_open_btn\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'
                         r'(.*?)\)\s*\)', src, re.S):
        icon, name, rest = m.group(1), m.group(2), m.group(3)
        km = re.search(r'key\s*=\s*"([^"]*)"', rest)
        out.append((name, km.group(1) if km else name))
    return out


def test_open_btn_calls_are_parsed():
    """先确认解析到了东西 —— 解析为空的话下面全都是假通过"""
    calls = _open_btn_calls()
    assert len(calls) >= 15, "只解析到 %d 个按钮，正则可能失效了：%s" % (
        len(calls), calls[:5])


def test_every_settings_button_resolves(win):
    """设置里每个入口按钮都要能在 commands 里找到可调用的入口

    这条就是抓"静默置灰"的那一条。
    """
    calls = _open_btn_calls()
    cmds = win._panel_commands()
    dead = [(name, key) for name, key in calls
            if not callable(cmds.get(key))]
    assert not dead, (
        "设置里有 %d 个按钮点不动（查不到入口）：\n  %s\n"
        "改法：要么在 _panel_commands 里补上这个键，"
        "要么给 _open_btn 传 key= 指向正确的键。"
        % (len(dead), "\n  ".join("%s -> 查 '%s' 没找到" % (n, k)
                                  for n, k in dead)))


def test_disabled_button_says_why():
    """万一真缺入口，tooltip 要写清缺的是哪个键（否则无从排查）"""
    src = open(SETTINGS, encoding="utf-8").read()
    src += open(os.path.join(os.path.dirname(SETTINGS), "settings_widgets.py"),
                encoding="utf-8").read()
    assert "没找到入口" in src, \
        "置灰时的提示里没有说明缺哪个键 —— 出问题会查不到原因"


def test_command_palette_entries_are_callable(win):
    """命令面板拿到的命令表里，值要么可调用、要么明确为 None"""
    cmds = win._panel_commands()
    assert cmds, "命令表是空的"
    bad = [k for k, v in cmds.items() if v is not None and not callable(v)]
    assert not bad, "这些入口既不是 None 也不可调用：%s" % bad
    usable = [k for k, v in cmds.items() if callable(v)]
    assert len(usable) >= 15, "可用的入口只有 %d 个：%s" % (len(usable), usable)


def test_settings_dialog_actually_enables_them(win):
    """端到端：真的建一次设置窗口，确认这些按钮没被置灰

    前面几条是"查表能查到"，这条是"界面上真的是可点的" ——
    两者差一层：_open_btn 里还有 setEnabled(False) 的分支。
    """
    from PyQt5.QtWidgets import QPushButton, QDialog
    import gui.settings_dialog as sd

    d = None
    made = []

    def _fake_dlg(title="", w=0, h=0):
        from PyQt5.QtWidgets import QVBoxLayout
        dd = QDialog()
        dd.setWindowTitle(title or "设置")
        lay = QVBoxLayout(dd)
        made.append(dd)
        return dd, lay

    # show_settings_dialog 结尾会 exec_()（模态等用户关窗口）——
    # 必须桩掉，否则这个用例会**永远挂住**（实测跑进后台 300 秒没退）。
    # 和 test_gui_smoke.py 里是同一个坑。
    saved_exec = QDialog.exec_
    QDialog.exec_ = lambda self: 0
    try:
        sd.show_settings_dialog(win, _fake_dlg, win.trunk, BASE, "小6",
                                None, None, None, None, None,
                                win._panel_commands())
        assert made, "设置窗口没建出来"
        btns = made[0].findChildren(QPushButton)
        dead = [b.text() for b in btns
                if not b.isEnabled() and "不可用" in (b.toolTip() or "")]
        assert not dead, "设置里有按钮被置灰了：%s" % dead
    finally:
        QDialog.exec_ = saved_exec
        for dd in made:
            try:
                dd.close()
            except Exception:
                pass


def test_system_and_developer_tabs_are_distinct(win, monkeypatch):
    """系统页和开发者页不能复用同一个 builder（否则内容完全一样）。"""
    from PyQt5.QtWidgets import QDialog, QTabWidget, QPushButton
    import gui.settings_dialog as sd
    from gui import ui_mode
    monkeypatch.setattr(ui_mode, "get_ui_mode", lambda *a, **k: "advanced")

    made = []

    def _fake_dlg(title="", w=0, h=0):
        from PyQt5.QtWidgets import QVBoxLayout
        dd = QDialog()
        dd.setWindowTitle(title or "设置")
        lay = QVBoxLayout(dd)
        made.append(dd)
        return dd, lay

    saved_exec = QDialog.exec_
    QDialog.exec_ = lambda self: 0
    try:
        sd.show_settings_dialog(
            win, _fake_dlg, win.trunk, BASE, "小6", None, None, None,
            None, None, win._panel_commands())
        tabs = made[0].findChild(QTabWidget)
        labels = [tabs.tabText(i) for i in range(tabs.count())]
        assert " 系统" in labels and " 开发者" in labels
        sys_page = tabs.widget(labels.index(" 系统"))
        dev_page = tabs.widget(labels.index(" 开发者"))
        assert sys_page is not dev_page
        sys_btns = [b.text() for b in sys_page.findChildren(QPushButton)]
        dev_btns = [b.text() for b in dev_page.findChildren(QPushButton)]
        assert any("系统" in t for t in sys_btns)
        assert not any("命令面板" in t for t in sys_btns)
        assert any("命令面板" in t for t in dev_btns)
    finally:
        QDialog.exec_ = saved_exec
        for dd in made:
            try:
                dd.close()
            except Exception:
                pass


def test_set_dialog_reuses_visible_window(win):
    """重复点设置按钮时，不重复构造窗口。"""
    from PyQt5.QtWidgets import QDialog
    import gui.settings_dialog as sd

    d = QDialog(win)
    d.setWindowTitle("设置")
    d.show()
    win._settings_dialog = d
    called = []
    old = sd.show_settings_dialog
    sd.show_settings_dialog = lambda *a, **k: called.append(1)
    try:
        out = win.set_dialog()
        assert out is d
        assert called == []
    finally:
        sd.show_settings_dialog = old
        win._settings_dialog = None
        d.close()
