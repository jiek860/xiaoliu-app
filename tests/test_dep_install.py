# -*- coding: utf-8 -*-
"""缺依赖时的"要不要现在装"：识别 + 弹框 + 不骚扰

为什么做这个
------------
改之前：功能点不动 -> 聊天里出现一行字
    「识别图片文字」缺一个可选组件（opencv-python），当前没装
    下一步：装上它（走国内源，快）：py -3 -m pip install ...
用户得**自己开命令行**、复制粘贴。很多人到这一步就放弃了 —— 功能白做。

改之后：同一个时机弹一个框
    需要「刚才那个功能」用到的一个组件：opencv-python（约 112 MB）
    [现在装]  [复制命令]  [以后再说]
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "libs"))
sys.path.insert(0, os.path.join(BASE, "optional_libs"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication          # noqa: E402
_app = QApplication.instance() or QApplication(sys.argv)

from core.error_text import missing_package      # noqa: E402
from gui.dep_dialog import package_size_hint     # noqa: E402

MIRROR = "tuna.tsinghua.edu.cn"


# ══════════════════════════════════════════════════════════════
# ① 包名识别 —— 认错比不认更糟
# ══════════════════════════════════════════════════════════════
SHOULD_FIND = [
    ("ModuleNotFoundError: No module named 'cv2'", "opencv-python"),
    ("No module named faster_whisper", "faster-whisper"),
    ("No module named 'PIL'", "Pillow"),
    ("No module named win32api", "pywin32"),
    ("No module named 'edge_tts'", "edge-tts"),
    ("「识别图片文字」缺一个可选组件（opencv-python），当前没装",
     "opencv-python"),
    ("没装 uiautomation。", "uiautomation"),
    ("缺少 pyaudio（语音输入要用）。", "pyaudio"),
    ("RSA 模式需要 cryptography 库。", "cryptography"),
]


@pytest.mark.parametrize("text,want", SHOULD_FIND,
                         ids=[w for _t, w in SHOULD_FIND])
def test_detects_package(text, want):
    assert missing_package(text) == want, \
        "%r 应该认出 %s，实际 %r" % (text[:40], want, missing_package(text))


def test_pip_command_is_enough_on_its_own():
    """**明写的 pip 命令本身就是最强信号**，不该再过"信号词闸门"

    ⚠️ 第一版把闸门放在最前面，结果这句被挡掉了：
        "未检测到语音识别后端。py -3 -m pip install ... faster-whisper"
    —— 明明明写了 pip 命令，却因为句子里没有闸门认得的词而返回空。
    """
    text = ("未检测到语音识别后端。\n"
            "py -3 -m pip install --target optional_libs faster-whisper "
            "-i https://pypi.tuna.tsinghua.edu.cn/simple")
    assert missing_package(text) == "faster-whisper"


SHOULD_NOT_FIND = [
    "这是一个完全正常的回复，没有任何依赖问题",
    "连接超时了，重试一次",
    "计算结果是 42",
    "",
    "文件保存成功",
    "缺少参数：请提供文件名",          # "缺少" 会命中闸门，但里面没有包名
    "需要先打开一个网页",              # "需要" 同上
]


@pytest.mark.parametrize("text", SHOULD_NOT_FIND)
def test_does_not_guess(text):
    """认不出就返回空 —— **不猜**（猜错会让用户装一个不相干的包）"""
    got = missing_package(text)
    assert got == "", "%r 不该认出包名，实际认成 %r" % (text[:36], got)


def test_reverse_name_mapping_is_right():
    """import 名 -> pip 名 的转换要对（报错里给的是 import 名）"""
    for imp, pip in [("cv2", "opencv-python"), ("PIL", "Pillow"),
                     ("win32api", "pywin32"), ("faster_whisper",
                                               "faster-whisper"),
                     ("edge_tts", "edge-tts")]:
        assert missing_package("No module named '%s'" % imp) == pip, imp


# ══════════════════════════════════════════════════════════════
# ② 大小提示 —— 得让用户知道要下多大
# ══════════════════════════════════════════════════════════════
def test_size_hint_for_heavy_packages():
    """重包必须报出量级（torch 491 MB 不能含糊）"""
    assert "491" in package_size_hint("torch")
    assert "112" in package_size_hint("opencv-python")
    assert "143" in package_size_hint("faster-whisper")


def test_size_hint_never_says_zero_mb():
    """⚠️ 小包不能显示成 "约 0 MB"

    第一版用 %d 格式化，uiautomation 的 0.2 变成了 "0 MB" ——
    界面上显示"约 0 MB"很滑稽。
    """
    for pkg in ("uiautomation", "jedi", "pyperclip", "comtypes"):
        h = package_size_hint(pkg)
        assert "0 MB" not in h, "%s 显示成 %r" % (pkg, h)
        assert "MB" in h, h


def test_size_hint_unknown_package():
    assert package_size_hint("某个完全没见过的包") == "大小未知"


# ══════════════════════════════════════════════════════════════
# ③ 弹框本身
# ══════════════════════════════════════════════════════════════
def _dlg(pkg="opencv-python", base=None):
    from gui.dep_dialog import DepInstallDialog
    return DepInstallDialog(None, pkg, feature="识别图片文字",
                            base=base or BASE)


def test_dialog_shows_package_and_size():
    d = _dlg()
    texts = " ".join(w.text() for w in d.findChildren(type(d.lbl)))
    assert "opencv-python" in texts, texts
    assert "MB" in texts, "没告诉用户要下多大：%s" % texts
    d.close()


def test_dialog_has_three_choices():
    """三个出口：现在装 / 复制命令 / 以后再说

    ⚠️ 「复制命令」是**文字链接**不是按钮 —— 它是次要逃生口
    （在这里装失败、或想自己控制时用），和主按钮并列会让用户多犹豫一次。
    这个项目对按钮数有硬预算，能省一个是一个。
    """
    from PyQt5.QtWidgets import QPushButton
    d = _dlg()
    labels = [b.text() for b in d.findChildren(QPushButton)]
    for want in ("现在装", "以后再说"):
        assert want in labels, "缺按钮 %s：%s" % (want, labels)
    assert "复制命令" not in labels, \
        "「复制命令」又变成按钮了（它该是文字链接）：%s" % labels
    assert "复制命令" in d.lnk_copy.text(), \
        "找不到「复制命令」链接：%s" % d.lnk_copy.text()
    d.close()


def test_copy_puts_command_with_mirror_on_clipboard():
    d = _dlg()
    d._copy()
    got = QApplication.clipboard().text()
    assert MIRROR in got, "复制的命令没有国内源：%s" % got
    assert "opencv-python" in got, got
    assert "--target" in got, "没装进项目的 optional_libs：%s" % got
    d.close()


def test_later_returns_later():
    d = _dlg()
    d._later()
    assert d.chosen == "later", d.chosen


def test_checkbox_means_never_ask_again():
    """勾了"以后不再问我这个组件"就该记住"""
    d = _dlg()
    d.chk.setChecked(True)
    d._later()
    assert d.chosen == "never", d.chosen


def test_install_runs_off_the_gui_thread():
    """装包要几十秒到几分钟，**不能在 GUI 线程里跑**（会卡死界面）

    这条只做静态检查（真跑一次 pip 要联网、要几分钟，不适合放进测试套件）。
    """
    src = open(os.path.join(BASE, "gui", "dep_dialog.py"),
               encoding="utf-8").read()
    assert "QThread" in src, "没看到线程"
    assert "class _Installer(QThread)" in src, "装包没放进 QThread"
    assert "_thread.start()" in src, "线程起了但没 start"


def test_dialog_does_not_block_on_construct():
    """建框本身必须瞬间返回（真装是点按钮之后的事）"""
    import time
    t0 = time.time()
    d = _dlg()
    dt = time.time() - t0
    d.close()
    assert dt < 2.0, "建这个框用了 %.2f 秒 —— 不该在这里做网络/安装动作" % dt
