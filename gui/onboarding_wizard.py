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

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QGroupBox, QRadioButton, QComboBox

from core import model_setup


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
    """首次运行引导向导"""

    # 后台探测 Ollama 完成后，用它把结果送回主线程
    # （Qt 控件只能在主线程碰，工作线程只负责发信号）
    probe_done = pyqtSignal(dict, str)

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("欢迎使用小6智能体 · 先花一分钟配好模型")
        self.setMinimumSize(660, 520)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self._build_pages()
        self.currentIdChanged.connect(self._on_page_changed)
        self.probe_done.connect(self._apply_local_status)

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
        gl.addWidget(QPushButton("🔄 重新检测", clicked=self._recheck))
        l2.addWidget(self.grp_local)

        # 方式二：云端 API
        self.grp_cloud = QGroupBox("方式二 · 云端 API（要自己申请 Key）")
        gc = QVBoxLayout(self.grp_cloud)
        self.rb_cloud = QRadioButton("用云端 API")
        gc.addWidget(self.rb_cloud)
        gc.addWidget(QLabel("以智谱 GLM 为例，地址填："
                            "https://open.bigmodel.cn/api/paas/v4/chat/completions"))
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
        self.ed_cloud_url.setText(str(cfg.get("cloud_url", "") or ""))
        self.ed_cloud_model.setText(str(cfg.get("cloud_model", "") or ""))
        if str(cfg.get("model_mode", "")).find("云端") >= 0:
            self.rb_cloud.setChecked(True)
        else:
            self.rb_local.setChecked(True)
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

    def _download_steps(self):
        """没装/没模型时给**能照着做**的步骤

        对比同类程序的做法：它们把 Ollama 的下载和模型下载都做成了
        程序内一键完成（带进度条、装完自动刷进下拉框）。小6 这边暂时
        还是引导用户自己去官网装 —— 那就至少把步骤写清楚：
        点哪、粘什么、大约多大、装完回到哪一步。
        含糊的"去装个 Ollama"是这一环最劝退的地方。
        """
        return (
            "要装的话按这个顺序来：<br>"
            "&nbsp;&nbsp;1. 打开 <a href='%s'>%s</a>，下载 Windows 版并安装<br>"
            "&nbsp;&nbsp;2. 装完 Ollama 会自己在后台运行（托盘会有个小图标）<br>"
            "&nbsp;&nbsp;3. 按 <code>Win+R</code> 输入 <code>cmd</code> 回车，粘贴这一行：<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<code>ollama run %s</code><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;（约 2GB，下载时窗口里会有进度条，走完就行）<br>"
            "&nbsp;&nbsp;4. 回到这里点「🔄 重新检测」，模型会自动出现在上面的下拉框里"
            % (model_setup.OLLAMA_DOWNLOAD, model_setup.OLLAMA_DOWNLOAD,
               model_setup.RECOMMENDED_LOCAL_MODEL))

    def _recheck(self):
        self._refresh_local_status()

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
