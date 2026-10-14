# -*- coding: utf-8 -*-
"""缺依赖时的"要不要现在装"对话框

为什么做这个
------------
改之前：功能点不动 → 聊天里出现一行字
    「识别图片文字」缺一个可选组件（opencv-python），当前没装
    下一步：装上它（走国内源，快）：py -3 -m pip install ... 
用户得**自己开命令行**、复制粘贴。很多人到这一步就放弃了 —— 功能就白做了。

改之后：同一个时机弹一个框
    需要「识别图片文字」用到的一个组件：opencv-python（约 112 MB）
    [现在装]  [复制命令]  [以后再说]
点「现在装」就地装好，装完这个功能立刻能用。

安全考虑（为什么不做成全自动静默下载）
    · pip 是从网上拉代码并在你机器上执行 —— 该让用户知情
    · torch 一个包 491 MB，静默下 500 MB 说不过去
    · 所以：**用户点一下** + **告诉他多大** + **可以拒绝**
"""
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout,
                             QLabel, QProgressBar, QPushButton, QVBoxLayout)

from core import error_text

MIRROR = error_text.PIP_MIRROR


def package_size_hint(pkg):
    """这个包大概多大（能查到就报，查不到说"大小未知"）

    为什么要报大小：torch 491 MB、opencv 112 MB、jedi 不到 1 MB ——
    不告诉用户就让他点"现在装"，是不负责任的。
    """
    # 粗略分级即可 —— 精确值要联网查，为一句提示不值当
    heavy = {"torch": 491, "opencv-python": 112,
             "faster-whisper": 143, "playwright": 80,
             "uiautomation": 0.2, "jedi": 0.5,
             "pyautogui": 5, "Pillow": 10,
             "cryptography": 12, "pyaudio": 1,
             "av": 63, "huggingface-hub": 5,
             "pywin32": 10, "pyperclip": 0.1, "comtypes": 0.5,
             "edge-tts": 3, "openai-whisper": 60}

    def _fmt(mb):
        # ⚠️ 不能用 %d —— uiautomation 是 0.2，会被格式化成 "0 MB"
        #    （第一版就是这么写的，界面上显示"约 0 MB"很滑稽）
        return "约 %s MB" % (("%d" % mb) if mb >= 1 else ("%.1f" % mb))

    try:
        from core import optional_deps as od
        for _feat, pkgs in od.FEATURES.items():
            if pkg in pkgs and pkg in heavy:
                return _fmt(heavy[pkg])
    # 静默是故意的：取不到大小不是错误 —— 这一句只是提示语里的
    # "约 XXX MB"，拿不到就走下面的兜底/显示"大小未知"，
    # 不该因此拦住安装流程
    except Exception:
        pass
    # 兜底：不在 FEATURES 映射里的包也要能报大小
    # （torch 就是 —— 它只是"看图"那条路的可选替代后端，没进功能映射）
    if pkg in heavy:
        return _fmt(heavy[pkg])
    return "大小未知"


class _Installer(QThread):
    """后台装包（pip 装大包要几十秒到几分钟，不能卡住界面）"""

    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, pkg, target_dir):
        super().__init__()
        self.pkg = pkg
        self.target_dir = target_dir

    def run(self):
        try:
            from pip._internal.cli.main import main as pip_main
        except Exception as e:
            self.done.emit(False, "pip 不可用：%s" % str(e)[:80])
            return
        args = ["install", "--quiet", "--disable-pip-version-check",
                "-i", MIRROR]
        if self.target_dir:
            args += ["--target", self.target_dir]
        args.append(self.pkg)
        self.progress.emit("正在下载安装 %s…（国内源）" % self.pkg)
        try:
            rc = pip_main(args)
        except SystemExit as e:                       # pip 内部会 sys.exit
            rc = int(getattr(e, "code", 1) or 0)
        except Exception as e:
            self.done.emit(False, "%s: %s" % (type(e).__name__, str(e)[:100]))
            return
        if rc == 0:
            # 装完把目录加进 sys.path，这样**当前进程**立刻就能 import
            import sys
            if self.target_dir and self.target_dir not in sys.path:
                sys.path.insert(0, self.target_dir)
            self.done.emit(True, "装好了，再试一次刚才那个功能就行")
        else:
            self.done.emit(False, "装失败（pip 返回 %s）。"
                                 "可以把命令复制出来手动跑，看看具体报错" % rc)


class DepInstallDialog(QDialog):
    """缺依赖时弹的框：现在装 / 复制命令 / 以后再说"""

    def __init__(self, parent, pkg, feature="", base=None, remember=True):
        super().__init__(parent)
        self.pkg = pkg
        self.base = base or os.getcwd()
        self.chosen = ""                 # "installed" / "later" / "never"
        self.setWindowTitle("这个功能需要一个组件")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        title = QLabel("<b>%s</b> 需要装一个组件"
                       % (feature or "刚才那个功能"))
        lay.addWidget(title)

        info = QLabel("组件：<code>%s</code>　%s"
                      % (pkg, package_size_hint(pkg)))
        info.setWordWrap(True)
        lay.addWidget(info)

        tip = QLabel("走国内源（清华），装进程序的 optional_libs 目录 —— "
                     "不会污染你系统里的 Python。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#64748b;")
        lay.addWidget(tip)

        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setVisible(False)
        lay.addWidget(self.lbl)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)          # 不确定进度（pip 不给百分比）
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        h = QHBoxLayout()
        self.btn_install = QPushButton("现在装")
        self.btn_install.setDefault(True)
        self.btn_install.clicked.connect(self._install)
        h.addWidget(self.btn_install)

        self.btn_later = QPushButton("以后再说")
        self.btn_later.clicked.connect(self._later)
        h.addWidget(self.btn_later)
        h.addStretch(1)
        lay.addLayout(h)

        # 「复制命令」做成**文字链接**而不是按钮：
        # 它是次要逃生口（在这里装失败 / 想自己控制时用），
        # 和主按钮「现在装」并列会让用户多犹豫一次。
        # 也顺带少占一个按钮预算（这个项目对按钮数有硬预算）。
        self.lnk_copy = QLabel(
            "装不了？<a href='#copy'>复制命令</a>自己跑")
        self.lnk_copy.setOpenExternalLinks(False)
        self.lnk_copy.linkActivated.connect(lambda _u: self._copy())
        lay.addWidget(self.lnk_copy)

        self.chk = QCheckBox("以后不再问我这个组件")
        if not remember:
            self.chk.setVisible(False)
        lay.addWidget(self.chk)

        self._thread = None

    # ---- 动作 ----
    def _install(self):
        self.btn_install.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_later.setEnabled(False)
        self.bar.setVisible(True)
        self.lbl.setVisible(True)
        self.lbl.setText("正在准备…")
        self.lbl.setStyleSheet("color:#475569;")

        target = os.path.join(self.base, "optional_libs")
        try:
            os.makedirs(target, exist_ok=True)
        except Exception:
            target = None                 # 建不出来就装到当前环境
        self._thread = _Installer(self.pkg, target)
        self._thread.progress.connect(lambda m: self.lbl.setText(m))
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _on_done(self, ok, msg):
        self.bar.setVisible(False)
        self.lbl.setText(("✅ " if ok else "❌ ") + msg)
        self.lbl.setStyleSheet("color:#16a34a;" if ok else "color:#dc2626;")
        self.btn_later.setText("关闭")
        self.btn_later.setEnabled(True)
        if ok:
            self.chosen = "never" if self.chk.isChecked() else "installed"
            self.btn_install.setVisible(False)
            self.btn_copy.setVisible(False)

    def _copy(self):
        cmd = error_text.install_cmd(self.pkg)
        try:
            QApplication.clipboard().setText(cmd)
            self.lbl.setVisible(True)
            self.lbl.setText("命令已复制，粘到命令行里跑就行：\n%s" % cmd)
            self.lbl.setStyleSheet("color:#16a34a;")
        except Exception as e:
            self.lbl.setVisible(True)
            self.lbl.setText("复制失败（%s）。命令是：\n%s"
                             % (str(e)[:40], cmd))
            self.lbl.setStyleSheet("color:#dc2626;")

    def _later(self):
        if not self.chosen:
            self.chosen = "never" if self.chk.isChecked() else "later"
        self.accept()

    def closeEvent(self, e):
        if not self.chosen:
            self.chosen = "never" if self.chk.isChecked() else "later"
        super().closeEvent(e)


def show_dep_dialog(parent, pkg, feature="", base=None):
    """给外部用的入口：弹框并返回用户选择（默认装到 <base>/optional_libs）

    返回 "installed" / "later" / "never"。
    """
    if not pkg:
        return ""
    d = DepInstallDialog(parent, pkg, feature=feature, base=base)
    d.exec_()
    return d.chosen
