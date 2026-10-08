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
想重新看一遍：删掉它，或从「功能中心 → 首次设置向导」打开。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
                             QLabel, QComboBox, QLineEdit, QPushButton,
                             QMessageBox, QApplication, QGroupBox, QRadioButton)

from core import model_setup


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

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("欢迎使用小6智能体 · 先花一分钟配好模型")
        self.setMinimumSize(660, 520)
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self._build_pages()
        self.currentIdChanged.connect(self._on_page_changed)

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
        gl.addWidget(QLabel(
            "没装的话：<a href='%s'>下载 Ollama</a>，装完在命令行执行 "
            "<code>ollama run %s</code>（会把模型下下来，约 2GB）"
            % (model_setup.OLLAMA_DOWNLOAD, model_setup.RECOMMENDED_LOCAL_MODEL)))
        hl = QHBoxLayout()
        hl.addWidget(QLabel("地址："))
        self.ed_ollama = QLineEdit()
        self.ed_ollama.setPlaceholderText(model_setup.DEFAULT_OLLAMA)
        hl.addWidget(self.ed_ollama, 1)
        hl.addWidget(QLabel("模型："))
        self.ed_local_model = QLineEdit()
        self.ed_local_model.setPlaceholderText(model_setup.RECOMMENDED_LOCAL_MODEL)
        hl.addWidget(self.ed_local_model, 1)
        gl.addLayout(hl)
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
        hc.addWidget(self.ed_cloud_url, 1)
        gc.addLayout(hc)
        hc2 = QHBoxLayout()
        hc2.addWidget(QLabel("模型："))
        self.ed_cloud_model = QLineEdit()
        self.ed_cloud_model.setPlaceholderText("glm-4-flash")
        hc2.addWidget(self.ed_cloud_model, 1)
        hc2.addWidget(QLabel("Key："))
        self.ed_cloud_key = QLineEdit()
        self.ed_cloud_key.setEchoMode(QLineEdit.Password)
        hc2.addWidget(self.ed_cloud_key, 1)
        gc.addLayout(hc2)
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
        self.ed_local_model.setText(str(cfg.get("local_model", "") or ""))
        self.ed_cloud_url.setText(str(cfg.get("cloud_url", "") or ""))
        self.ed_cloud_model.setText(str(cfg.get("cloud_model", "") or ""))
        if str(cfg.get("model_mode", "")).find("云端") >= 0:
            self.rb_cloud.setChecked(True)
        else:
            self.rb_local.setChecked(True)
        self._refresh_local_status()

    def _refresh_local_status(self):
        url = self.ed_ollama.text().strip() or model_setup.DEFAULT_OLLAMA
        info = model_setup.probe_ollama(url, timeout=3)
        if info["reachable"]:
            n = len(info["models"])
            if n:
                self.lbl_local_status.setText(
                    "✅ 连上了，已装 %d 个模型：%s"
                    % (n, "、".join(info["models"][:5])))
                self.lbl_local_status.setStyleSheet("color:#16a34a;")
            else:
                self.lbl_local_status.setText(
                    "⚠️ Ollama 在跑，但还没有任何模型。执行 "
                    "<code>ollama run %s</code> 下载一个。"
                    % model_setup.RECOMMENDED_LOCAL_MODEL)
                self.lbl_local_status.setStyleSheet("color:#d97706;")
        else:
            self.lbl_local_status.setText(
                "❌ 连不上 %s。没装 Ollama 就点上面的下载链接；装好了但没启动，"
                "就启动它再点「重新检测」。" % url)
            self.lbl_local_status.setStyleSheet("color:#dc2626;")

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
                    model=self.ed_local_model.text().strip()
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
                "「功能中心 → 首次设置向导」重新打开这一页。")

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
