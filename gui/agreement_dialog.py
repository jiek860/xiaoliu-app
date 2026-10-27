# -*- coding: utf-8 -*-
"""协议确认对话框 - 首次启动/版本更新时弹窗"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QTextBrowser, QTabWidget, QMessageBox,
)
from PyQt5.QtCore import Qt

from gui.feedback_states import make_action_links


class AgreementDialog(QDialog):
    """隐私政策 + 用户协议确认对话框"""

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("小6智能体 · 用户协议与隐私政策")
        self.setMinimumSize(720, 640)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
        )
        self.agreed = False
        self._build_ui()

    def _build_ui(self):
        from core.agreement import Agreement
        ag = Agreement(self.trunk)
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("欢迎使用小6智能体")
        title.setStyleSheet("font-size:18px;font-weight:bold;padding:6px;")
        layout.addWidget(title)

        tip = QLabel(
            "首次使用或协议更新时，请阅读并同意以下协议。\n"
            "您必须同意《隐私政策》和《用户协议》才能继续使用。"
        )
        tip.setStyleSheet("color:#475569;font-size:12px;padding:4px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        # 标签页
        tabs = QTabWidget()

        privacy_tb = QTextBrowser()
        privacy_tb.setReadOnly(True)
        privacy_tb.setPlainText(ag.read_privacy())
        privacy_tb.setStyleSheet(
            "font-family:'Microsoft YaHei UI';font-size:13px;"
            "background:#fafafa;border:1px solid #e5e6eb;"
        )
        tabs.addTab(privacy_tb, "📋 隐私政策 v%s" % ag.get_status()["当前隐私版本"])

        terms_tb = QTextBrowser()
        terms_tb.setReadOnly(True)
        terms_tb.setPlainText(ag.read_terms())
        terms_tb.setStyleSheet(
            "font-family:'Microsoft YaHei UI';font-size:13px;"
            "background:#fafafa;border:1px solid #e5e6eb;"
        )
        tabs.addTab(terms_tb, "📜 用户协议 v%s" % ag.get_status()["当前用户协议版本"])

        layout.addWidget(tabs, stretch=1)

        # 复选框：两份协议合并勾一次。原来两个勾选框并排，
        # 用户要点两下才能继续，且「请勾选以上两项」得来回看。
        # 两份协议本身在标签页里都能点开读完，勾选只是"我读过了"的声明。
        self.cb_privacy = QCheckBox("我已阅读并同意《用户协议》和《隐私政策》")
        self.cb_privacy.setStyleSheet("font-size:13px;")
        layout.addWidget(self.cb_privacy)
        # 兼容旧属性名（老代码/测试可能还按 cb_terms 取）
        self.cb_terms = self.cb_privacy

        self.cb_privacy.stateChanged.connect(self._update_buttons)

        # 提示
        self.hint = QLabel("请勾选上方复选框后点击「同意并继续」")
        self.hint.setStyleSheet("color:#c00;font-size:12px;padding:4px;")
        layout.addWidget(self.hint)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        # 「不同意并退出」是低频负向出口 → 链接；正向的「同意并继续」才是主按钮
        btn_row.addWidget(make_action_links([
            ("不同意并退出", self._on_disagree),
        ]))
        self.btn_agree = QPushButton("同意并继续")
        self.btn_agree.setStyleSheet(
            "padding:8px 20px;background:#4a9eff;color:white;"
            "border:none;border-radius:6px;font-size:13px;"
        )
        self.btn_agree.clicked.connect(self._on_agree)
        self.btn_agree.setEnabled(False)
        btn_row.addWidget(self.btn_agree)

        layout.addLayout(btn_row)

    def _update_buttons(self):
        ok = self.cb_privacy.isChecked() and self.cb_terms.isChecked()
        self.btn_agree.setEnabled(ok)
        if ok:
            self.hint.setText("✅ 已勾选，可以点击「同意并继续」")
            self.hint.setStyleSheet("color:#16a34a;font-size:12px;padding:4px;")
        else:
            self.hint.setText("请勾选上方复选框后点击「同意并继续」")
            self.hint.setStyleSheet("color:#c00;font-size:12px;padding:4px;")

    def _on_agree(self):
        from core.agreement import Agreement
        ag = Agreement(self.trunk)
        user = "guest"
        try:
            if self.trunk:
                r = self.trunk.call("auth", "whoami")
                if isinstance(r, dict):
                    user = r.get("user", "guest")
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        ag.agree(user=user)
        self.agreed = True
        self.accept()

    def _on_disagree(self):
        from core.agreement import Agreement
        ag = Agreement(self.trunk)
        ag.disagree()
        r = QMessageBox.question(
            self, "确认退出",
            "您不同意《隐私政策》和《用户协议》，将无法使用本软件。\n\n"
            "确定退出吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if r == QMessageBox.Yes:
            self.agreed = False
            self.reject()
