# -*- coding: utf-8 -*-
"""首次运行引导向导

为什么重写
----------
原来这个文件里的 OnboardingWizard 是死代码（全项目没有任何地方实例化它），
而且内容也不解决问题：它只有一句"选择模型模式"的下拉框，另外还摆了两个
"匿名使用统计"之类的开关，却**完全没帮用户把模型配通**。结果是朋友解压后
打开 → 登录 → 问它话没反应 → 回来问你。

新版目标只有一个：**让用户在这儿就把模型配到能用，或者明确知道差什么。**

三道页：
    1. 欢迎 + 说明数据都在本地
    2. 模型配置（核心）—— 实时自检，本地 Ollama / 云端 API 两条路都能当场配
    3. 结果 —— 通了就说可以开始，没通就说清楚缺什么、怎么补、可以以后再说

标记文件 data/.guide_done 存在时不再打扰（开发者机器上已经有了）。
想重新看一遍：删掉它，或从「设置 → 系统 → 首次设置向导」打开。
"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
import threading

from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtWidgets import QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QGroupBox, QRadioButton, QComboBox, QProgressBar

from core import model_setup, ollama_installer

from gui.feedback_states import make_action_links


def _model_text(w):
    """从"可能是 QLineEdit、也可能是可编辑 QComboBox"的控件里取值"""
    return (w.currentText() if hasattr(w, "currentText") else w.text()).strip()


def _set_model_text(w, s):
    """往上面那种控件里填值"""
    s = str(s or "")
    if hasattr(w, "setEditText"):
        w.setEditText(s)
    else:
        w.setText(s)


def marker_path(trunk):
    """标记文件位置：跟着 data 目录走（Trunk 里 data_dir 默认就是 base/data）"""
    d = getattr(trunk, "data_dir", None)
    if not d:
        base = getattr(trunk, "base", None) or os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(base, "data")
    return os.path.join(d, ".guide_done")


def needs_onboarding(trunk):
    """是否该弹引导：没标记过 且 模型还不能用"""
    if os.path.exists(marker_path(trunk)):
        return False
    try:
        return not model_setup.check(trunk, probe=False)["ready"]
    except Exception:
        return False


def mark_done(trunk):
    try:
        p = marker_path(trunk)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("ok")
    except Exception as e:
        _x6_swallowed(__name__, e)
        pass


from gui.onboarding_local import OnboardingLocalMixin
from gui.onboarding_install import OnboardingInstallMixin
from gui.onboarding_final import OnboardingFinalMixin
from gui.onboarding_provider import OnboardingProviderMixin


class OnboardingWizard(
    OnboardingLocalMixin,
    OnboardingInstallMixin,
    OnboardingFinalMixin,
    OnboardingProviderMixin,
    QWizard,
):
    """首次运行引导向导

    ⚠️ 窗口尺寸是**量出来的，不是猜的**
    ----------------------------------
    原来写的是 setMinimumSize(660, 520) —— 一个手写的猜测值。
    实测「配置模型」页的内容需要 **620 x 628**，而向导外壳
    （标题栏 + 页标题 + 底部按钮栏）另占 **22 x 99**。
    所以窗口至少要 **642 x 727**，而 520 的高度差了 207 px。

    后果（用户截图报的）：内容被裁 → 底部出现横向滚动条 →
    右侧出现纵向滚动条 → 说明文字和输入框被截断，
    "看着就是坏的"。

    现在改成按各页 sizeHint 现算，并且**状态文字变长后重算一次**
    （"没装 Ollama"那四步说明会让页面明显变高）。
    """

    CHROME_W = 24

    CHROME_H = 102

    probe_done = pyqtSignal(dict, str)

    dl_prog = pyqtSignal(float, float, float, float)

    dl_msg = pyqtSignal(str)

    dl_done = pyqtSignal(dict)

    pull_prog = pyqtSignal(str, float, float, int, float)

    pull_done = pyqtSignal(dict)

    cloud_test_done = pyqtSignal(dict)

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("欢迎使用小6智能体 · 先花一分钟配好模型")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self._build_pages()
        # 两个单选分属不同分组框，Qt 的 autoExclusive 管不到它们
        # （用户能同时勾上两个，保存时云端悄悄赢）—— 这里手动互斥。
        self.rb_local.toggled.connect(self._sync_mode_radios)
        self.rb_cloud.toggled.connect(self._sync_mode_radios)
        # 尺寸按内容算（别再手写猜测值 —— 见类文档里那段实测数据）
        self.fit_to_content(grow=True)
        self.currentIdChanged.connect(self._on_page_changed)
        self.probe_done.connect(self._apply_local_status)
        self.dl_prog.connect(self._on_dl_progress)
        self.dl_msg.connect(lambda m: self.lbl_dl.setText(m))
        self.dl_done.connect(self._on_dl_done)
        self.pull_prog.connect(self._on_pull_progress)
        self.pull_done.connect(self._on_pull_done)
        self.cloud_test_done.connect(self._apply_cloud_test)
        self._dl_busy = False
        self._dl_stop = False
        self._dl_ready_path = None
        self._dl_kind = ""
        # ⚠️ 延时重算尺寸用**挂在 self 上的 QTimer**，不用 QTimer.singleShot
        # ------------------------------------------------------------------
        # 必须延时：刚 setText 完，页面 sizeHint 还是**旧文字**的尺寸，
        # 那一刻算出来的最小尺寸不够（实测：四步说明需要 811px 高，
        # 但立刻算只得 690px，文字被裁 67px）。
        #
        # 但不能用 QTimer.singleShot —— 它创建的定时器**没有父对象**，
        # 活得比控件久：控件销毁后回调才触发，去碰已析构的 C++ 对象，
        # **整个进程硬崩**（Windows fatal exception: access violation，
        # 退出码 0xC0000005，pytest 跑到 59% 直接没输出，连是哪个用例都打不出来）。
        #
        # 挂在 self 上的 QTimer 会随控件一起销毁，回调不可能打到死对象。
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(lambda: self.fit_to_content(grow=True))

    def _build_pages(self):
        # ---- 第 1 页：欢迎 ----
        p1 = QWizardPage()
        p1.setTitle("欢迎使用")
        l1 = QVBoxLayout(p1)
        l1.addWidget(QLabel("<h2>👋 你好，小6在你电脑上安家了</h2>"))
        l1.addWidget(QLabel(
            "开始聊天前需要先配一个「大脑」（模型），否则它收到消息也没法回你。\n"
            "这一步只做一次，大概一分钟。\n"))
        tip = QLabel(
            "· 所有聊天记录和记忆都只存在你这台电脑上，不会上传\n"
            "· 免费的走法是装一个 Ollama（本地模型，不联网也能用）\n"
            "· 也可以填自己的云端 API（效果更好，按量付费）")
        tip.setStyleSheet("color:#475569;line-height:170%;")
        l1.addWidget(tip)

        # 新手要在第一屏就知道接下来三步是什么，而不是只看到功能列表。
        steps = QLabel(
            "<b>新手三步</b><br>"
            "&nbsp;&nbsp;1. 在下一页配好模型（本地 Ollama / 云端 API 二选一）<br>"
            "&nbsp;&nbsp;2. 点「保存并检测」，看到绿色配置完成<br>"
            "&nbsp;&nbsp;3. 回到聊天框说一句话；复杂目标切到「任务」模式")
        steps.setWordWrap(True)
        steps.setStyleSheet(
            "background:#eff6ff;color:#1e3a8a;border-radius:6px;"
            "padding:8px;line-height:165%;")
        l1.addWidget(steps)

        compat = QLabel(
            "<b>兼容性速查</b>　Windows 10/11 ✅　Python 3.10 / 3.11 / 3.12 ✅<br>"
            "macOS / Linux 的聊天和部分文件功能可能可用，但电脑控制、窗口操作、"
            "截图等桌面能力不是当前支持目标。<br>"
            "旧数据启动时会先自动备份再按 v0→v1→v2 迁移；"
            "插件只接受签名且 API 版本兼容的模块。<br>"
            "8 类模型服务商、RAG 管理、团队管理和用量成本："
            "设置 → 模型，或按 Ctrl+K 搜对应名称。")
        compat.setWordWrap(True)
        compat.setStyleSheet("color:#7c2d12;line-height:165%;")
        l1.addWidget(compat)
        # 指向那份面向用户的小白说明。
        # 项目里原本只有 700 行的《架构与功能说明》—— 那是给改代码的人看的，
        # 用户没法从里面查到"怎么配模型""某个功能在哪个菜单"。
        doc = QLabel(
            "📖 更完整的用法（怎么用、功能在哪、出问题怎么查）见项目里的 "
            "<b>使用说明-小白版.txt</b>，"
            "也可以从「设置 → 系统 → 使用说明（小白版）」直接打开。")
        doc.setWordWrap(True)
        doc.setStyleSheet("color:#64748b;line-height:170%;")
        l1.addWidget(doc)
        l1.addStretch(1)
        self.addPage(p1)

        # ---- 第 2 页：模型配置 ----
        p2 = QWizardPage()
        p2.setTitle("配置模型（两种方式选一个）")
        l2 = QVBoxLayout(p2)

        # 方式一：本地 Ollama
        self.grp_local = QGroupBox("方式一 · 本地 Ollama（免费，推荐）")
        gl = QVBoxLayout(self.grp_local)
        self.rb_local = QRadioButton("用本地 Ollama")
        self.rb_local.setChecked(True)
        gl.addWidget(self.rb_local)
        self.lbl_local_status = QLabel()
        self.lbl_local_status.setWordWrap(True)
        gl.addWidget(self.lbl_local_status)
        self.lbl_local_howto = QLabel()
        self.lbl_local_howto.setWordWrap(True)
        self.lbl_local_howto.setOpenExternalLinks(True)
        gl.addWidget(self.lbl_local_howto)

        # ── 一键下载 Ollama 安装包（带进度）──
        # 对比同类程序后补上的：它们把这一步做成了程序内一键完成。
        # 小6 原来只给一句"去官网下载"，用户得自己开浏览器找、
        # 下 1.5GB、再开命令行 —— 这是最劝退的一环。
        # 进度条就放在向导里，不开新窗口。
        self.lbl_dl = QLabel()
        self.lbl_dl.setWordWrap(True)
        self.lbl_dl.setVisible(False)
        gl.addWidget(self.lbl_dl)
        self.bar_dl = QProgressBar()
        self.bar_dl.setRange(0, 100)
        self.bar_dl.setVisible(False)
        gl.addWidget(self.bar_dl)
        hdl = QHBoxLayout()
        # 只放一个按钮：下载/安装按状态换动作。
        # 原来做成三个（下载/安装/取消），下载完再冒出一个"安装"——
        # 多一个按钮多一分犹豫，而且"下完了当然就该装"。
        # 「取消下载」只有下载中才出现，属于低频兜底 → 做成链接。
        self.btn_dl = QPushButton("⬇️ 一键下载 Ollama 安装包")
        self.btn_dl.setToolTip(
            "约 %d MB。自动选国内加速源（实测比官网快 100 倍以上），"
            "下完这个按钮会变成「📦 立即安装」。" % ollama_installer.APPROX_MB)
        self.btn_dl.clicked.connect(self._on_dl_button)
        hdl.addWidget(self.btn_dl)
        self.btn_cancel_dl = make_action_links(
            [("取消下载", self._cancel_download)])
        self.btn_cancel_dl.setVisible(False)
        hdl.addWidget(self.btn_cancel_dl)
        hdl.addStretch(1)
        gl.addLayout(hdl)

        # ⚠️ 地址和模型**必须各占一行**。
        #    原来是一行塞 4 个控件（地址：|输入框|模型：|输入框），
        #    两个输入框都设了 stretch=1，窗口一窄就被压成几十像素 ——
        #    用户看到的是 "http://localhost:..." 和 "qwen2.5-coder..." 两条
        #    截断的残影，根本没法核对和修改（用户截图报的就是这个）。
        #    云端那边本来就是拆两行的，本地这边是漏了。
        hl = QHBoxLayout()
        hl.addWidget(QLabel("地址："))
        self.ed_ollama = QLineEdit()
        self.ed_ollama.setPlaceholderText(model_setup.DEFAULT_OLLAMA)
        self.ed_ollama.setMinimumWidth(240)      # 下限，防被压成条
        hl.addWidget(self.ed_ollama, 1)
        gl.addLayout(hl)

        hl2 = QHBoxLayout()
        hl2.addWidget(QLabel("模型："))
        # 用**可编辑下拉框**：检测到 Ollama 里有哪些模型就自动填进去，
        # 用户点一下就能选，不用照着文档手打模型名（打错了就是"没反应"）。
        # 仍然可编辑 —— 自己训的模型名照样能填。
        self.ed_local_model = QComboBox()
        self.ed_local_model.setEditable(True)
        self.ed_local_model.setMinimumWidth(240)
        self.ed_local_model.setToolTip(
            "检测到本地已有模型时会自动列出来，点一下即可选中；"
            "也可以手动输入自己的模型名")
        hl2.addWidget(self.ed_local_model, 1)
        gl.addLayout(hl2)
        hr = QHBoxLayout()
        # 「重新检测」「下载模型」都是辅助动作 → 链接。
        # 「⬇️ 下载模型」原来要用户自己开 cmd 跑 `ollama run qwen2.5:3b`：
        # 要会开命令行、会粘命令、看着黑窗口，还得自己判断什么时候算下完。
        # 现在复用上面那套进度条和取消链接（两种下载互斥，不会同时进行）。
        hr.addWidget(make_action_links([
            ("🔄 重新检测", self._recheck),
            ("⬇️ 下载模型", self._start_pull),
        ]))
        hr.addStretch(1)
        gl.addLayout(hr)
        l2.addWidget(self.grp_local)

        # 方式二：云端 API
        self.grp_cloud = QGroupBox("方式二 · 云端 API（要自己申请 Key）")
        gc = QVBoxLayout(self.grp_cloud)
        self.rb_cloud = QRadioButton("用云端 API")
        gc.addWidget(self.rb_cloud)

        # ── 常见服务商预设：选一个就自动填好"地址 + 模型名"──
        # 原来只有一句"以智谱 GLM 为例，地址填：https://…"，
        # 用户得自己把 URL 抄进输入框（抄错一个字符就是 404，很难查）。
        # 这里列的每一家地址都**实测过**（发不带 Key 的请求返回 401 = 地址有效）。
        hp = QHBoxLayout()
        hp.addWidget(QLabel("服务商："))
        self.cb_provider = QComboBox()
        self.cb_provider.addItems(model_setup.provider_names())
        self.cb_provider.setMinimumWidth(240)
        self.cb_provider.setToolTip("选一个，下面的地址和模型名会自动填好；"
                                    "也可以选「自定义」自己填")
        self.cb_provider.currentTextChanged.connect(self._apply_provider)
        hp.addWidget(self.cb_provider, 1)
        gc.addLayout(hp)

        self.lbl_provider_tip = QLabel()
        self.lbl_provider_tip.setWordWrap(True)
        self.lbl_provider_tip.setOpenExternalLinks(True)
        gc.addWidget(self.lbl_provider_tip)

        hc = QHBoxLayout()
        hc.addWidget(QLabel("地址："))
        self.ed_cloud_url = QLineEdit()
        self.ed_cloud_url.setMinimumWidth(240)
        hc.addWidget(self.ed_cloud_url, 1)
        gc.addLayout(hc)
        # 同样拆行：模型和 Key 各占一行，不然窄窗口下两个都会被压扁
        hc2 = QHBoxLayout()
        hc2.addWidget(QLabel("模型："))
        self.ed_cloud_model = QLineEdit()
        self.ed_cloud_model.setPlaceholderText("glm-4-flash")
        self.ed_cloud_model.setMinimumWidth(240)
        hc2.addWidget(self.ed_cloud_model, 1)
        gc.addLayout(hc2)
        hc3 = QHBoxLayout()
        hc3.addWidget(QLabel("Key："))
        self.ed_cloud_key = QLineEdit()
        self.ed_cloud_key.setEchoMode(QLineEdit.Password)
        self.ed_cloud_key.setMinimumWidth(240)
        self.ed_cloud_key.setPlaceholderText("在服务商后台申请，形如 xxxxxxxx.xxxxxxxx")
        hc3.addWidget(self.ed_cloud_key, 1)
        gc.addLayout(hc3)
        l2.addWidget(self.grp_cloud)

        l2.addWidget(QPushButton("💾 保存并检测", clicked=self._save_and_check))
        self.lbl_result = QLabel()
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setStyleSheet("padding:6px;border-radius:4px;")
        l2.addWidget(self.lbl_result)
        # ── 真连一次云端 ──
        # 「保存并检测」只看配置齐不齐：Key 少一位也显示 ready，
        # 用户要到第一次聊天才知道 401，而那时只看到一句"出了点问题"。
        # 这里给一个当场验证的入口；用动作链接而不是按钮（按钮预算只许降）。
        self.lbl_cloud_test = QLabel()
        self.lbl_cloud_test.setWordWrap(True)
        self.lbl_cloud_test.setVisible(False)
        l2.addWidget(self.lbl_cloud_test)
        self.lnk_cloud_test = make_action_links([
            ("测试云端 Key 是否可用（真发一次请求）", self._test_cloud)])
        self.lnk_cloud_test.setVisible(False)
        l2.addWidget(self.lnk_cloud_test)
        self.rb_cloud.toggled.connect(self._update_cloud_test_visible)
        self.rb_local.toggled.connect(self._update_cloud_test_visible)
        l2.addStretch(1)
        self.addPage(p2)

        # ---- 第 3 页：完成 ----
        p3 = QWizardPage()
        p3.setTitle("完成")
        l3 = QVBoxLayout(p3)
        self.lbl_final = QLabel()
        self.lbl_final.setWordWrap(True)
        self.lbl_final.setStyleSheet("line-height:170%;")
        l3.addWidget(self.lbl_final)
        l3.addStretch(1)
        self.addPage(p3)

def show_onboarding(trunk, parent=None):
    """弹出首次设置向导；返回 True 表示用户走完了向导。

    ⚠️ 这个函数曾经被删掉，但 `gui/main_window.py` 和
    `gui/mixins/dialog_mixin.py` 还在 `from gui.onboarding_wizard import
    needs_onboarding, show_onboarding` —— 于是每次启动都会在日志里留下
    "首次引导检查失败: cannot import name 'show_onboarding'"，而且
    **新用户永远看不到配模型向导**（模型没配好就发消息没反应）。
    这里恢复它，并保持原来的返回语义：走完 -> True，取消/关闭 -> False。
    """
    try:
        wiz = OnboardingWizard(trunk, parent)
    except Exception:
        # 向导自己构造失败不该拦住程序启动
        try:
            if trunk is not None:
                trunk._log("首次向导打开失败")
        except Exception:  # 静默是故意的
            pass
        return False
    from PyQt5.QtWidgets import QDialog
    finished = wiz.exec_() == QDialog.Accepted
    if finished:
        try:
            mark_done(trunk)
        except Exception as e:
            _x6_swallowed(__name__, e)
    return bool(finished)
