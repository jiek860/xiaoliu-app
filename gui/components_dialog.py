# -*- coding: utf-8 -*-
"""功能扩展组件 / 环境依赖窗口

入口：设置 -> 系统 -> 可选组件（或 Ctrl+K 搜「可选组件」）。

这里集中放三类东西：
  1. Python 包：核心依赖 + 可选功能。检测状态、单个安装、一键装全部未装
  2. 外部程序：Python / Ollama / Node / uv / Playwright 内核  给下载页
  3. 镜像地址：pip / HuggingFace / Playwright / npm / 模型站  一键复制

安装走 gui/dep_dialog.py 的 _Installer（QThread），不卡界面：
  - 核心依赖装进当前解释器
  - 可选组件装进项目的 optional_libs/（不污染系统 Python）
"""
import importlib.util
import os
import webbrowser

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from gui.dep_dialog import _Installer
from gui.feedback_states import make_action_links

# (分组, 显示名, import 名, pip 规格, 装到哪, 大小)
PACKAGES = [
    # ---- 核心依赖（必需的，缺了程序起不来）----
    ("核心依赖（必需）", "PyQt5", "PyQt5", "PyQt5", "system", "142 MB"),
    ("核心依赖（必需）", "requests", "requests", "requests", "system", "1 MB"),
    ("核心依赖（必需）", "numpy", "numpy", "numpy", "system", "40 MB"),
    ("核心依赖（必需）", "cryptography", "cryptography", "cryptography", "system", "10 MB"),
    ("核心依赖（必需）", "psutil", "psutil", "psutil", "system", "0.4 MB"),
    # ---- 语音识别 ----
    ("语音识别", "faster-whisper", "faster_whisper", "faster-whisper", "optional", "143 MB"),
    ("语音识别", "av（必须 <19）", "av", "av<19", "optional", "63 MB"),
    ("语音识别", "huggingface-hub（必须 <2）", "huggingface_hub",
     "huggingface-hub<2", "optional", "5 MB"),
    ("语音识别", "pyaudio（麦克风）", "pyaudio", "pyaudio", "optional", "1 MB"),
    # ---- 语音合成 ----
    ("语音合成", "edge-tts", "edge_tts", "edge-tts", "optional", "3 MB"),
    # ---- 浏览器自动化 ----
    ("浏览器自动化", "playwright", "playwright", "playwright", "optional", "80 MB"),
    # ---- 看图 / 多模态 ----
    ("看图 / 多模态", "opencv-python", "cv2", "opencv-python", "optional", "112 MB"),
    ("看图 / 多模态", "Pillow", "PIL", "Pillow", "optional", "10 MB"),
    # ---- 电脑控制 ----
    ("电脑控制", "pyautogui", "pyautogui", "pyautogui", "optional", "5 MB"),
    ("电脑控制", "pyperclip", "pyperclip", "pyperclip", "optional", "0.1 MB"),
    ("电脑控制", "pywin32", "win32api", "pywin32", "optional", "10 MB"),
    # ---- 代码补全 ----
    ("代码补全", "jedi", "jedi", "jedi", "optional", "0.5 MB"),
]

# (名称, 说明, 下载页)
EXTERNALS = [
    ("Python 3.10+", "程序运行环境（安装时务必勾 Add Python to PATH）",
     "https://www.python.org/downloads/"),
    ("Ollama", "本地模型运行环境（免费、断网也能用）",
     "https://ollama.com/download/windows"),
    ("Playwright Chromium", "浏览器自动化内核（装完 playwright 后在命令行跑 "
                            "py -3 -m playwright install chromium）",
     "https://playwright.dev/python/docs/browsers"),
    ("Node.js", "MCP 的 npx 需要它", "https://nodejs.org/zh-cn/download"),
    ("uv / uvx", "MCP 的 uvx 需要它",
     "https://docs.astral.sh/uv/getting-started/installation/"),
    ("Git for Windows", "可选：拉取 / 更新代码", "https://git-scm.com/download/win"),
    ("VC++ 运行库", "可选：某些库缺 DLL 时需要",
     "https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist"),
]

# (名称, 地址)
MIRRORS = [
    ("pip 清华源", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("pip 阿里源", "https://mirrors.aliyun.com/pypi/simple"),
    ("pip 中科大源", "https://pypi.mirrors.ustc.edu.cn/simple"),
    ("HuggingFace 镜像", "https://hf-mirror.com"),
    ("Playwright 镜像", "https://cdn.npmmirror.com/binaries/playwright"),
    ("npm 镜像", "https://registry.npmmirror.com"),
    ("魔搭社区（模型）", "https://modelscope.cn"),
    ("Ollama 模型库", "https://ollama.com/library"),
]


def _installed(mod):
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def missing_optional_packages():
    """还没装的可选组件：[(显示名, pip 规格), ...]

    设置窗口「依赖」页只用这个摘要（逐行「安装」按钮留在这个窗口里，
    设置页的按钮预算只有主操作那几个，不能被十几行安装按钮撑爆）。
    """
    out = []
    for group, name, mod, spec, target, size in PACKAGES:
        if group.startswith("核心依赖"):
            continue
        if not _installed(mod):
            out.append((name, spec))
    return out


class ComponentsDialog(QDialog):
    def __init__(self, parent=None, base=None, install_component=None):
        super().__init__(parent)
        self.base = base or os.getcwd()
        self.opt_dir = os.path.join(self.base, "optional_libs")
        self._threads = []
        self._queue = []
        self._rows = []
        self._last_fail = None
        self.setWindowTitle("\U0001F9E9 功能扩展组件 / 环境依赖")
        self.setMinimumSize(780, 780)
        self._build()

    # ---------------- 界面 ----------------
    def _build(self):
        outer = QVBoxLayout(self)

        intro = QLabel(
            "核心依赖装进当前 Python；可选组件装进项目的 optional_libs/ "
            "（不污染系统环境）。安装统一走清华镜像，大包已标注大小。")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#475569;font-size:12px;")
        outer.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        box_w = QWidget()
        box = QVBoxLayout(box_w)
        box.setSpacing(2)
        scroll.setWidget(box_w)
        outer.addWidget(scroll, 1)

        # ---- Python 包 ----
        last = None
        for group, name, mod, spec, target, size in PACKAGES:
            if group != last:
                h = QLabel("<b>%s</b>" % group)
                h.setStyleSheet("color:#1e40af;padding-top:8px;")
                box.addWidget(h)
                last = group
            box.addWidget(self._pkg_row(name, mod, spec, target, size))

        # ---- 外部程序 ----
        h = QLabel("<b>外部程序（需要手动装）</b>")
        h.setStyleSheet("color:#1e40af;padding-top:12px;")
        box.addWidget(h)
        for name, desc, url in EXTERNALS:
            box.addWidget(self._ext_row(name, desc, url))

        # ---- 镜像地址 ----
        h = QLabel("<b>镜像地址（点「复制」拿走）</b>")
        h.setStyleSheet("color:#1e40af;padding-top:12px;")
        box.addWidget(h)
        for name, url in MIRRORS:
            box.addWidget(self._mirror_row(name, url))

        box.addStretch(1)

        # ---- 底部 ----
        bottom = QHBoxLayout()
        self._one = make_action_links([
            ("⚡ 一键安装全部未装组件", self._install_all)])
        bottom.addWidget(self._one)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.RichText)
        self._status.setOpenExternalLinks(False)
        self._status.linkActivated.connect(self._copy_cmd)
        self._status.setStyleSheet("color:#475569;font-size:11px;")
        bottom.addWidget(self._status, 1)

        bottom.addWidget(QLabel("Esc 关闭"))
        outer.addLayout(bottom)

    def _pkg_row(self, name, mod, spec, target, size):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 1, 0, 1)
        row.addWidget(QLabel("%s  <span style='color:#94a3b8;font-size:11px;'>约 %s</span>"
                             % (name, size)), 1)
        ok = _installed(mod)
        st = QLabel("已装" if ok else "未装")
        st.setStyleSheet("color:#16a34a;" if ok else "color:#94a3b8;")
        st.setFixedWidth(44)
        row.addWidget(st)
        btn = QPushButton("已装" if ok else "安装")
        btn.setFixedWidth(72)
        btn.setEnabled(not ok)
        rec = {"name": name, "mod": mod, "pip": spec, "target": target,
               "status": st, "btn": btn, "installed": ok}
        btn.clicked.connect(lambda _, r=rec: self._install_one(r))
        row.addWidget(btn)
        self._rows.append(rec)
        return w

    def _ext_row(self, name, desc, url):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 1, 0, 1)
        lab = QLabel("%s  <span style='color:#94a3b8;font-size:11px;'>%s</span>"
                     % (name, desc))
        lab.setWordWrap(True)
        row.addWidget(lab, 1)
        # 「打开下载页」是一次性跳转 → 链接，不占按钮位
        row.addWidget(make_action_links([
            ("打开下载页", lambda _u=url: webbrowser.open(_u)),
        ]))
        return w

    def _mirror_row(self, name, url):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 1, 0, 1)
        lab = QLabel("%s  <span style='color:#94a3b8;font-size:11px;'>%s</span>"
                     % (name, url))
        lab.setWordWrap(True)
        row.addWidget(lab, 1)
        row.addWidget(make_action_links([
            ("复制", lambda _u=url: self._copy(_u)),
        ]))
        return w

    # ---------------- 动作 ----------------
    def _copy(self, url):
        try:
            QApplication.clipboard().setText(url)
        except (AttributeError, RuntimeError) as e:
            self._status.setText("复制失败：%s" % str(e)[:60])
            return
        self._status.setText("已复制：" + url)

    def _copy_cmd(self, _link=None):
        """把这次失败的那条安装命令复制出来，方便用户自己排查

        必须走 core.error_text.install_cmd 这个统一入口（自带国内源）
        自己拼 "pip install" 字符串会被 test_dep_hints 的守卫拦下。
        """
        rec = getattr(self, "_last_fail", None)
        if not rec:
            return
        from core.error_text import install_cmd
        target = None if rec.get("target") == "system" else "optional_libs"
        cmd = install_cmd(rec["pip"], target=target)
        if not cmd:
            return
        try:
            QApplication.clipboard().setText(cmd)
        except (AttributeError, RuntimeError) as e:
            self._status.setText("复制失败：%s" % str(e)[:60])
            return
        self._status.setText("命令已复制：" + cmd)

    def _target_dir(self, target):
        if target == "system":
            return None
        try:
            os.makedirs(self.opt_dir, exist_ok=True)
        except OSError:
            return None
        return self.opt_dir

    def _spawn(self, rec, from_queue):
        rec["btn"].setEnabled(False)
        rec["btn"].setText("下载中...")
        self._status.setText("正在安装 %s（走清华源，请稍候）..." % rec["name"])
        t = _Installer(rec["pip"], self._target_dir(rec["target"]))
        self._threads.append(t)
        t.progress.connect(lambda m: self._status.setText(m))
        t.done.connect(lambda ok, msg, r=rec, q=from_queue:
                       self._on_done(ok, msg, r, q))
        t.start()

    def _install_one(self, rec):
        if rec["installed"]:
            return
        self._spawn(rec, False)

    def _install_all(self):
        pending = [r for r in self._rows if not r["installed"]]
        if not pending:
            self._status.setText("没有需要安装的，全部已就绪")
            return
        self._queue = list(pending)
        self._one.setEnabled(False)
        self._start_next()

    def _start_next(self):
        if not self._queue:
            self._one.setEnabled(True)
            self._status.setText("全部处理完了（失败的可以单独点「重试」）")
            return
        rec = self._queue.pop(0)
        if rec["installed"]:
            self._start_next()
            return
        self._spawn(rec, True)

    def _on_done(self, ok, msg, rec, from_queue):
        now = _installed(rec["mod"])
        rec["installed"] = now
        if now:
            rec["status"].setText("已装")
            rec["status"].setStyleSheet("color:#16a34a;")
            rec["btn"].setText("已装")
            rec["btn"].setEnabled(False)
        else:
            rec["status"].setText("失败" if not ok else "装完但导入失败")
            rec["status"].setStyleSheet("color:#dc2626;")
            rec["btn"].setText("重试")
            rec["btn"].setEnabled(True)
        if ok:
            self._status.setText(msg)
        else:
            self._last_fail = rec
            self._status.setText(
                "失败：%s　<a href='#copy'>复制安装命令</a>" % str(msg)[:120])
        if from_queue:
            self._start_next()


def show_components_dialog(parent, base, install_component=None):
    """功能扩展组件 / 环境依赖窗口（保留原签名，install_component 不再使用）"""
    d = ComponentsDialog(parent, base, install_component)
    d.exec_()
