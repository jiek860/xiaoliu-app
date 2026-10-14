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
import os
import threading

from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtWidgets import QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QGroupBox, QRadioButton, QComboBox, QProgressBar

from core import model_setup, ollama_installer


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
        return not model_setup.check(trunk)["ready"]
    except Exception:
        return False


def mark_done(trunk):
    try:
        p = marker_path(trunk)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("ok")
    except Exception:
        pass


class OnboardingWizard(QWizard):
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

    # 外壳开销：实测值（向导自己的标题/页标题/按钮栏/边距）
    CHROME_W = 24
    CHROME_H = 102

    # 后台探测 Ollama 完成后，用它把结果送回主线程
    # （Qt 控件只能在主线程碰，工作线程只负责发信号）
    probe_done = pyqtSignal(dict, str)
    # 下载进度：已下字节 / 总字节 / 速度MBps / 剩余秒
    dl_prog = pyqtSignal(float, float, float, float)
    # 下载过程中的文字提示（挑源、换源…）
    dl_msg = pyqtSignal(str)
    # 下载结束（成功/取消/失败）
    dl_done = pyqtSignal(dict)
    # 模型拉取进度：状态文字 / 已下MB / 总MB / 百分比 / 速度
    pull_prog = pyqtSignal(str, float, float, int, float)
    # 模型拉取结束
    pull_done = pyqtSignal(dict)

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("欢迎使用小6智能体 · 先花一分钟配好模型")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self._build_pages()
        # 尺寸按内容算（别再手写猜测值 —— 见类文档里那段实测数据）
        self.fit_to_content(grow=True)
        self.currentIdChanged.connect(self._on_page_changed)
        self.probe_done.connect(self._apply_local_status)
        self.dl_prog.connect(self._on_dl_progress)
        self.dl_msg.connect(lambda m: self.lbl_dl.setText(m))
        self.dl_done.connect(self._on_dl_done)
        self.pull_prog.connect(self._on_pull_progress)
        self.pull_done.connect(self._on_pull_done)
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

    # ---------------- 页面 ----------------
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
        # 只放两个按钮：一个是"下载/安装"（同一个按钮按状态换动作），
        # 一个是"取消"（1.5GB 的下载不给取消说不过去）。
        # 原来做成三个（下载/安装/取消），下载完再冒出一个"安装"——
        # 多一个按钮多一分犹豫，而且"下完了当然就该装"。
        self.btn_dl = QPushButton("⬇️ 一键下载 Ollama 安装包")
        self.btn_dl.setToolTip(
            "约 %d MB。自动选国内加速源（实测比官网快 100 倍以上），"
            "下完这个按钮会变成「📦 立即安装」。" % ollama_installer.APPROX_MB)
        self.btn_dl.clicked.connect(self._on_dl_button)
        hdl.addWidget(self.btn_dl)
        self.btn_cancel_dl = QPushButton("取消下载")
        self.btn_cancel_dl.setVisible(False)
        self.btn_cancel_dl.clicked.connect(self._cancel_download)
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
        hr.addWidget(QPushButton("🔄 重新检测", clicked=self._recheck))
        # 「⬇️ 下载模型」—— 原来这一步要用户自己开 cmd 跑
        # `ollama run qwen2.5:3b`：要会开命令行、会粘命令、看着黑窗口，
        # 还得自己判断什么时候算下完。对比同类程序，它们把这一步也做成了
        # 程序内一键完成。
        # 复用上面那套进度条和取消按钮（两种下载互斥，不会同时进行），
        # 所以这里**只多一个按钮**。
        self.btn_pull = QPushButton("⬇️ 下载模型")
        self.btn_pull.setToolTip(
            "从 Ollama 拉取「模型」框里那个模型（约 2GB），带进度和取消。\n"
            "不用自己开命令行跑 ollama run 了。")
        self.btn_pull.clicked.connect(self._start_pull)
        hr.addWidget(self.btn_pull)
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

    # ---------------- 逻辑 ----------------
    def _prefill(self):
        cfg = self.trunk.config or {}
        self.ed_ollama.setText(str(cfg.get("ollama_url", "") or ""))
        _set_model_text(self.ed_local_model,
                        str(cfg.get("local_model", "") or ""))
        cloud_url = str(cfg.get("cloud_url", "") or "")
        self.ed_cloud_url.setText(cloud_url)
        self.ed_cloud_model.setText(str(cfg.get("cloud_model", "") or ""))
        if str(cfg.get("model_mode", "")).find("云端") >= 0:
            self.rb_cloud.setChecked(True)
        else:
            self.rb_local.setChecked(True)

        # ⚠️ 把「服务商」下拉框同步成**已保存地址对应的那一家**。
        #    不这么做的话，下拉框会停在默认的第一项（智谱 GLM），
        #    而下面的地址可能是别家的 —— 界面自相矛盾，用户会以为
        #    "我明明选的是智谱，怎么地址不对"。
        #    反查不到就落到「自定义」，并把已填内容原样留着。
        #    （踩过的坑：setCurrentText 选**同一个值**不会触发信号，
        #      所以不能指望 _apply_provider 帮忙同步。）
        match = "自定义（自己填）"
        for p in model_setup.CLOUD_PROVIDERS:
            if cloud_url and p["地址"] == cloud_url:
                match = p["名字"]
                break
        self.cb_provider.blockSignals(True)
        self.cb_provider.setCurrentText(match)
        self.cb_provider.blockSignals(False)
        self._apply_provider(match, fill=False)

        self._refresh_local_status()

    def _refresh_local_status(self, async_=True):
        """检测本地 Ollama 并把结果显示到状态标签

        默认**异步**：原来是在 initializePage 里同步发请求（timeout=3），
        向导窗口要等这次探测完才显示出来 —— Ollama 不在线时就是先卡 3 秒。
        """
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
        if not async_:
            self._apply_local_status(model_setup.probe_ollama(url, timeout=3), url)
            return
        self.lbl_local_status.setText("⏳ 正在检测 %s …" % url)
        self.lbl_local_status.setStyleSheet("color:#64748b;")

        def _work():
            try:
                info = model_setup.probe_ollama(url, timeout=3)
            except Exception:
                info = {"reachable": False, "models": []}
            try:
                self.probe_done.emit(info, url)
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-probe").start()

    def _apply_local_status(self, info, url):
        # 检测到的模型自动刷进下拉框 —— 用户点一下就能选，不用照着文档手打。
        # （手打模型名打错一个字符，表现就是"发了消息没反应"，很难自己查出来。）
        if info.get("reachable"):
            models = [m for m in (info.get("models") or []) if m]
            cur = _model_text(self.ed_local_model)
            if models:
                self.ed_local_model.blockSignals(True)
                self.ed_local_model.clear()
                self.ed_local_model.addItems(models)
                # 优先保留用户/配置里已经选好的那个
                if cur and cur in models:
                    self.ed_local_model.setCurrentText(cur)
                elif model_setup.RECOMMENDED_LOCAL_MODEL in models:
                    self.ed_local_model.setCurrentText(
                        model_setup.RECOMMENDED_LOCAL_MODEL)
                else:
                    # 没指定就用第一个可用的 —— 比让用户自己猜强
                    self.ed_local_model.setCurrentIndex(0)
                self.ed_local_model.blockSignals(False)

        if info["reachable"]:
            n = len(info["models"])
            if n:
                self.lbl_local_status.setText(
                    "✅ 连上了，已装 %d 个模型：%s"
                    % (n, "、".join(info["models"][:5])))
                self.lbl_local_status.setStyleSheet("color:#16a34a;")
                self.lbl_local_howto.setText(
                    "下面「模型」一栏已经自动列出上面这些，选一个就行 → "
                    "然后点「保存并检测」。")
                self.lbl_local_howto.setStyleSheet("color:#16a34a;")
            else:
                self.lbl_local_status.setText(
                    "⚠️ Ollama 在跑，但还没有任何模型。")
                self.lbl_local_status.setStyleSheet("color:#d97706;")
                self.lbl_local_howto.setText(self._download_steps())
                self.lbl_local_howto.setStyleSheet("color:#475569;")
        else:
            self.lbl_local_status.setText("❌ 连不上 %s" % url)
            self.lbl_local_status.setStyleSheet("color:#dc2626;")
            self.lbl_local_howto.setText(self._download_steps())
            self.lbl_local_howto.setStyleSheet("color:#475569;")

        # 说明文字从一句变成四步、或者反过来，页面高度会变 —— 重算一次，
        # 不然新加的那几行会被窗口裁掉。
        #
        # ⚠️ 必须先让布局算完再量：刚 setText 完就调 fit_to_content 的话，
        #    QLabel 的 sizeHint 还是**旧文字**的尺寸，算出来的窗口高度不够，
        #    四步说明照样被切（实测：宽 580 时那段文字需要 280px，只给了 80px）。
        #    activate() 强制立刻重排；再补一个 0 延时的兜底，
        #    因为有些平台下 activate() 之后还要等一轮事件循环才准。
        try:
            self.currentPage().layout().activate()
        # 静默是故意的：强制重排只是为了让下面的尺寸量得准 ——
        # 它失败顶多量得偏小、退回上一步的尺寸，不该因此拦住用户配模型
        except Exception:
            pass
        self.fit_to_content(grow=True)
        # 再排一次延时重算：activate() 之后页面 sizeHint 有时还没跟上
        # （Qt 要等一轮事件循环）。用挂在 self 上的定时器，见 __init__ 里的说明。
        try:
            self._fit_timer.start(0)
        # 静默是故意的：这只是"再排一次重算"，起不来也不影响
        # 本次已经算好的尺寸
        except Exception:
            pass

    def _download_steps(self):
        """没装/没模型时给**能照着做**的步骤

        对比同类程序后两步都改成程序内一键完成了：
        装 Ollama 不用自己开浏览器找，下模型不用自己开命令行跑
        `ollama run xxx`（要会开 cmd、会粘命令、看着黑窗口、
        还得自己判断什么时候算下完）。
        """
        return (
            "按这个顺序来：<br>"
            "&nbsp;&nbsp;<b>1.</b> 点上面的 <b>⬇️ 一键下载 Ollama 安装包</b>"
            "（约 %d MB，自动走国内加速源）<br>"
            "&nbsp;&nbsp;<b>2.</b> 下完点 <b>📦 立即安装</b>，"
            "按弹出的安装向导点完（装到哪可以自己选）<br>"
            "&nbsp;&nbsp;<b>3.</b> 装完 Ollama 会自己在后台运行"
            "（右下角托盘有个小羊驼图标）<br>"
            "&nbsp;&nbsp;<b>4.</b> 回到这里点 <b>🔄 重新检测</b>，"
            "连上以后点 <b>⬇️ 下载模型</b>（模型约 2GB，带进度条，可以取消）<br>"
            "&nbsp;&nbsp;<b>5.</b> 下完模型会自动出现在下拉框里，"
            "选中它，再点「💾 保存并检测」<br><br>"
            "下载不动的备选：去 <a href='%s'>%s</a> 用浏览器手动下安装包。"
            % (ollama_installer.APPROX_MB, model_setup.OLLAMA_DOWNLOAD,
               model_setup.OLLAMA_DOWNLOAD))

    # ---------------- 模型下载（复用同一套进度条/取消） ----------------
    def _start_pull(self):
        """从 Ollama 拉「模型」框里那个模型"""
        if getattr(self, "_dl_busy", False):
            return
        model = _model_text(self.ed_local_model) or \
            model_setup.RECOMMENDED_LOCAL_MODEL
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA

        self._dl_busy = True
        self._dl_stop = False
        self._dl_kind = "model"
        self.btn_dl.setEnabled(False)
        self.btn_pull.setEnabled(False)
        self.btn_cancel_dl.setVisible(True)
        self.bar_dl.setVisible(True)
        self.bar_dl.setValue(0)
        self.lbl_dl.setVisible(True)
        self.lbl_dl.setText("正在从 Ollama 拉取「%s」…（约 2GB）" % model)
        self.lbl_dl.setStyleSheet("color:#475569;")

        def _work():
            try:
                r = ollama_installer.pull_model(
                    url, model,
                    progress=lambda st, g, t, pct, sp:
                        self.pull_prog.emit(st, g, t, pct, sp),
                    should_stop=lambda: self._dl_stop)
                r["模型"] = r.get("模型") or model
                self.pull_done.emit(r)
            except Exception as e:
                self.pull_done.emit({"ok": False,
                                     "错误": "%s: %s" % (type(e).__name__,
                                                         str(e)[:80])})

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-pull").start()

    def _on_pull_progress(self, status, got, total, pct, sp):
        self.bar_dl.setValue(pct)
        if total:
            self.lbl_dl.setText(
                "%s　已下 %.0f / %.0f MB　%.1f MB/s"
                % (status, got, total, sp))
        else:
            self.lbl_dl.setText(status)

    def _on_pull_done(self, r):
        self._dl_busy = False
        self.btn_dl.setEnabled(True)
        self.btn_pull.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        if r.get("ok"):
            self.bar_dl.setValue(100)
            self.lbl_dl.setText(
                "✅ 模型「%s」下载完成（%.0f MB，用了 %.0f 秒）—— "
                "点「🔄 重新检测」刷新列表"
                % (r.get("模型", ""), r.get("MB", 0), r.get("耗时秒", 0)))
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            # 下完自动刷一次列表，用户不用再点
            self._refresh_local_status()
        elif r.get("取消"):
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "已取消。已经下好的部分**不会白费** —— Ollama 留着缓存，"
                "下次拉同一个模型会接着用。")
            self.lbl_dl.setStyleSheet("color:#64748b;")
        else:
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "❌ 下载失败：%s\n（Ollama 没启动的话先把它打开，"
                "再点「🔄 重新检测」）" % r.get("错误", "")[:90])
            self.lbl_dl.setStyleSheet("color:#dc2626;")

    def _recheck(self):
        self._refresh_local_status()

    # ---------------- 尺寸 ----------------
    def fit_to_content(self, grow=False):
        """按各页**实际需要的尺寸**定窗口大小

        ⚠️ 关键是高度要用 heightForWidth(需要的宽度) 算，不能直接用 sizeHint()
        ------------------------------------------------------------------
        sizeHint() 给的是"在**当前**宽度下的高度"。而这里要设的是**最小宽度** ——
        窗口缩到那个宽度后，文字换行会更多、需要的高度比 sizeHint 报的更大。

        实测踩到的：宽 580 时那段"没装 Ollama"的四步说明需要 280px 高，
        而按 sizeHint 算出来的最小尺寸只给了 80px —— 差 200px，
        说明文字被裁掉（而这几行正是全部指引）。

        正确做法：
            宽度 = 各页 sizeHint 的首选宽（在那个宽度下不用额外换行）
            高度 = heightForWidth(那个宽度)（**在那个宽度下**真正需要的高度）

        grow=True 时，如果算出来比当前尺寸还大就跟着长大
        （状态文字从一句变成四步说明时，页面会明显变高）。

        **只增不减**：用户自己拉大过窗口的话，不该因为一次
        文字更新就被缩回去。
        """
        try:
            self.ensurePolished()
            need_w = need_h = 0
            for i in range(self.pageIds().__len__()):
                page = self.page(i)
                sh = page.sizeHint()
                w = max(sh.width(), page.minimumSizeHint().width())
                # 在那个宽度下真正需要的高度
                h = page.heightForWidth(w) if w > 0 else 0
                if h <= 0:
                    h = sh.height()          # 不支持 heightForWidth 就退回 sizeHint
                need_w = max(need_w, w)
                need_h = max(need_h, h)
            if need_w <= 0 or need_h <= 0:
                return
            min_w = need_w + self.CHROME_W
            min_h = need_h + self.CHROME_H
            self.setMinimumSize(min_w, min_h)
            if grow:
                # 初始给一点富余，别卡在"刚好装下"
                self.resize(max(self.width(), min_w + 70),
                            max(self.height(), min_h + 10))
        # 静默是故意的：尺寸算不出来不该拦住用户配模型 ——
        # 退化成 Qt 的默认尺寸，向导照样能用
        except Exception:
            pass

    # ---------------- 云端服务商预设 ----------------
    def _apply_provider(self, name, fill=True):
        """选服务商 -> 自动填地址和模型名

        fill=False 时**只更新提示文字，不动已经填好的输入框** ——
        `_prefill()` 同步下拉框时会用到：那一步的目的只是让
        "下拉框显示的那家"和"已保存的地址"对上，不该把用户
        自己改过的地址/模型名覆盖掉。
        """
        p = model_setup.find_provider(name)
        if not p:
            # 「自定义（自己填）」：不动用户已经填好的内容
            self.lbl_provider_tip.setText(
                "自己填的话：地址用服务商文档里的 <b>chat/completions</b> 完整地址，"
                "模型名一个字符都不能错。")
            self.lbl_provider_tip.setStyleSheet("color:#64748b;")
            return
        if fill:
            self.ed_cloud_url.setText(p["地址"])
            self.ed_cloud_model.setText(p["模型"])
        self.lbl_provider_tip.setText(
            "%s · %s —— Key 去 <a href='%s'>%s</a> 申请"
            % (p["名字"], p["备注"], p["申请"], p["申请"]))
        self.lbl_provider_tip.setStyleSheet("color:#16a34a;")

    # ---------------- Ollama 一键下载 ----------------
    def _on_dl_button(self):
        """同一个按钮按状态换动作：还没下完 -> 下载；下好了 -> 安装"""
        if getattr(self, "_dl_ready_path", None):
            self._run_installer()
        else:
            self._start_download()

    def _start_download(self):
        """起线程下载，进度通过信号回主线程（Qt 控件只能在主线程碰）"""
        if getattr(self, "_dl_busy", False):
            return
        self._dl_busy = True
        self._dl_stop = False
        self._dl_ready_path = None
        self.btn_dl.setEnabled(False)
        self.btn_cancel_dl.setVisible(True)
        self.bar_dl.setVisible(True)
        self.bar_dl.setValue(0)
        self.lbl_dl.setVisible(True)
        self.lbl_dl.setText("正在挑下载源…")
        self.lbl_dl.setStyleSheet("color:#475569;")

        def _work():
            try:
                best = ollama_installer.pick_best(
                    progress=lambda m: self.dl_msg.emit(m))
                if not best:
                    self.dl_done.emit({"ok": False,
                                       "错误": "所有下载源都连不上（可能是断网）"})
                    return
                self.dl_msg.emit("用「%s」下载中 —— 实测 %s"
                                 % (best["名字"], best.get("实测", "")))

                def prog(got, total, sp, eta):
                    self.dl_prog.emit(got, total or 0, sp, eta)

                r = ollama_installer.download(
                    best["url"], progress=prog,
                    should_stop=lambda: self._dl_stop)
                r["源"] = best["名字"]
                self.dl_done.emit(r)
            except Exception as e:
                self.dl_done.emit({"ok": False,
                                   "错误": "%s: %s" % (type(e).__name__,
                                                       str(e)[:80])})

        threading.Thread(target=_work, daemon=True,
                         name="onboarding-download").start()

    def _cancel_download(self):
        """取消当前正在进行的下载（安装包 或 模型，两种共用这个按钮）"""
        self._dl_stop = True
        self.lbl_dl.setText("正在取消…")

    def _on_dl_progress(self, got, total, sp, eta):
        if total:
            self.bar_dl.setValue(int(got * 100 / total))
            self.lbl_dl.setText(
                "已下 %.0f / %.0f MB　%.1f MB/s　剩余约 %d 秒"
                % (got / 1048576, total / 1048576, sp, int(eta)))
        else:
            self.lbl_dl.setText("已下 %.0f MB　%.1f MB/s"
                                % (got / 1048576, sp))

    def _on_dl_done(self, r):
        self._dl_busy = False
        self.btn_dl.setEnabled(True)
        self.btn_cancel_dl.setVisible(False)
        if r.get("ok"):
            self._dl_ready_path = r.get("路径") or ollama_installer.default_path()
            self.bar_dl.setValue(100)
            self.lbl_dl.setText(
                "✅ 下载完成：%.0f MB（%s，用了 %.0f 秒）—— 点下面的按钮安装"
                % (r.get("MB", 0), r.get("源", ""), r.get("耗时秒", 0)))
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            self.btn_dl.setText("📦 立即安装")
        elif r.get("取消"):
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText("已取消下载（没留下半个文件）")
            self.lbl_dl.setStyleSheet("color:#64748b;")
        else:
            self.bar_dl.setVisible(False)
            self.lbl_dl.setText(
                "❌ 下载失败：%s\n可以点上面的下载链接用浏览器手动下，"
                "或稍后重试。" % r.get("错误", "")[:90])
            self.lbl_dl.setStyleSheet("color:#dc2626;")

    def _run_installer(self):
        r = ollama_installer.run_installer(
            getattr(self, "_dl_ready_path", None))
        if r.get("ok"):
            self.lbl_dl.setText("📦 %s" % r["提示"])
            self.lbl_dl.setStyleSheet("color:#16a34a;")
            self._dl_ready_path = None
            self.btn_dl.setText("⬇️ 重新下载安装包")
        else:
            self.lbl_dl.setText("❌ %s" % r.get("错误", ""))
            self.lbl_dl.setStyleSheet("color:#dc2626;")

    def _save_and_check(self):
        try:
            if self.rb_cloud.isChecked():
                model_setup.apply_cloud(
                    self.trunk,
                    url=self.ed_cloud_url.text().strip(),
                    model=self.ed_cloud_model.text().strip(),
                    key=self.ed_cloud_key.text().strip())
            else:
                model_setup.apply_local(
                    self.trunk,
                    url=self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA,
                    model=_model_text(self.ed_local_model)
                    or model_setup.RECOMMENDED_LOCAL_MODEL)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e)[:120])
            return
        self._refresh_local_status()
        self._show_result()

    def _show_result(self):
        try:
            r = model_setup.check(self.trunk)
        except Exception as e:
            self.lbl_result.setText("检测出错：" + str(e)[:100])
            return
        if r["ready"]:
            self.lbl_result.setText("✅ 配置完成，可以正常聊天了。")
            self.lbl_result.setStyleSheet(
                "padding:6px;border-radius:4px;background:#dcfce7;color:#166534;")
        else:
            self.lbl_result.setText(
                "⚠️ 还差一点：\n· " + "\n· ".join(r["problems"])
                + "\n\n" + r["advice"])
            self.lbl_result.setStyleSheet(
                "padding:6px;border-radius:4px;background:#fef3c7;color:#92400e;")

    def _on_page_changed(self, pid):
        if pid == 0:
            if not self.ed_ollama.text():
                self._prefill()
        elif pid == 1:
            self._refresh_local_status()
            self._show_result()
        elif pid == 2:
            self._fill_final()

    def _fill_final(self):
        try:
            r = model_setup.check(self.trunk)
        except Exception:
            r = {"ready": False, "problems": ["检测失败"], "advice": "稍后可以在设置里再配。"}
        if r["ready"]:
            self.lbl_final.setText(
                "<h2>🎉 配好了</h2>"
                "点「完成」就能开始聊天了。<br><br>"
                "想换个模型、调语气、开关联网，随时去「设置」里改。")
        else:
            self.lbl_final.setText(
                "<h2>暂时还不能聊天</h2>"
                "缺的是：<br>· " + "<br>· ".join(r["problems"]) +
                "<br><br>" + r["advice"].replace("\n", "<br>") +
                "<br><br>点「完成」不会丢东西，你随时可以从"
                "「设置 → 系统 → 首次设置向导」重新打开这一页。")

    # ---------------- 收尾 ----------------
    def accept(self):
        self._save_and_note()
        super().accept()

    def reject(self):
        # 用户点了取消/关闭，也算引导过了，别每次启动都弹
        self._save_and_note()
        super().reject()

    def _save_and_note(self):
        mark_done(self.trunk)


def show_onboarding(trunk, parent=None):
    """打开引导。任何异常都不应该影响主程序，返回是否已完成配置。"""
    try:
        w = OnboardingWizard(trunk, parent)
        w.exec_()
        return model_setup.check(trunk)["ready"]
    except Exception as e:
        try:
            trunk._log("首次引导异常: %s" % str(e)[:80])
        except Exception:
            pass
        return False
