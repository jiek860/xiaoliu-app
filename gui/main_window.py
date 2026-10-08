# -*- coding: utf-8 -*-
"""主窗口 JarvisWindow —— 仅负责组装所有 Mixin 和初始化"""
import os
import json
import time
import threading
import traceback
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QApplication
from PyQt5.QtCore import pyqtSignal, QTimer
from PyQt5.QtGui import QIcon
from core.trunk import Trunk
from gui.mixins import (
    ChatMixin, DialogMixin, VoiceMixin, SystemMixin, LifecycleMixin,
)

STYLE = """
QMainWindow { background: #ffffff; }
QWidget { color: #1f1f1f; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QPushButton {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 6px; padding: 10px; color: #1f1f1f;
    font-size: 13px; text-align: left; padding-left: 15px;
}
QPushButton:hover { background: #f2f3f5; border: 1px solid #4a9eff; color: #4a9eff; }
QTextBrowser, QListWidget, QComboBox {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 8px; color: #1f1f1f;
}
QLineEdit {
    background: #ffffff; border: 1px solid #e5e6eb;
    border-radius: 6px; color: #1f1f1f; padding: 8px;
}
QDialog, QScrollArea { background: #ffffff; }
QLabel { color: #1f1f1f; font-size: 13px; }
QCheckBox { color: #1f1f1f; }
"""


class JarvisWindow(
    ChatMixin,
    DialogMixin,
    VoiceMixin,
    SystemMixin,
    LifecycleMixin,
    QMainWindow,
):
    confirmRequested = pyqtSignal(str, str)
    statusMessage = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        # 1. Trunk 初始化
        self.trunk = Trunk()
        self.base = getattr(self.trunk, "base", None) or \
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 2. 状态栏 + 线程安全回调
        self.statusMessage.connect(lambda s: self.statusBar().showMessage(s, 5000))
        self.trunk.status_cb = self.statusMessage.emit
        # 3. 插件市场
        try:
            self.trunk._load_lazy("plugin_market")
        except Exception:
            pass
        # 4. 危险操作确认信号
        self._confirm_evt = threading.Event()
        self._confirm_result = {"ok": False}
        self.confirmRequested.connect(self._ask_confirm)
        self.trunk.confirm_cb = self._confirm_wait
        # 5. 语音控制器
        from gui.speech import SpeechController
        self.speech = SpeechController(self.trunk, self)
        # 6. 窗口基础属性
        self.ai_name = self.trunk.config.get("ai_name", "Jarvis")
        self.setWindowTitle("✨ 小6智能体")
        _ico = os.path.join(self.base, "app.ico")
        if os.path.exists(_ico):
            self.setWindowIcon(QIcon(_ico))
        self.setMinimumSize(1100, 750)
        self.setStyleSheet(STYLE)
        # 7. 账号管理器（必须在build_ui之前）
        from gui.account import AccountManager
        self.account = AccountManager(self.trunk, self.base)
        # 7.5 兼容旧接口
        self.chat_store = self.account.chat_store
        self._chat_username = self.account.username
        self._chat_session = self.account.session
        # 8. 构建 UI
        from gui.build_ui import build_ui
        build_ui(self)

        # ===== 协议确认（首次启动/版本更新） =====
        try:
            from core.agreement import Agreement
            from gui.agreement_dialog import AgreementDialog
            ag = Agreement(self.trunk)
            if ag.need_show():
                dlg = AgreementDialog(self.trunk, self)
                dlg.exec_()
                if not dlg.agreed:
                    from PyQt5.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self, "退出",
                        "您未同意协议，程序将退出。"
                    )
                    from PyQt5.QtWidgets import QApplication
                    QApplication.quit()
                    return
        except Exception as e:
            try:
                self.trunk._log("协议确认失败: %s" % str(e)[:60])
            except Exception:
                pass

        # 9. 自动登录
        _auto_user = None
        try:
            cache = os.path.join(self.base, "data", "login_cache.json")
            if os.path.exists(cache):
                c = json.load(open(cache, encoding="utf-8"))
                r = self.trunk.call("auth", "login", c.get("u", ""))
                if isinstance(r, dict) and r.get("ok"):
                    _auto_user = r.get("user") or c.get("u", "")
                    self.account.switch_user(_auto_user)
                    try:
                        self.login_btn_sb.setText("🔑 " + str(_auto_user))
                    except Exception:
                        pass
        except Exception:
            pass
        # 10. 加载历史
        try:
            msgs = self.account.load_history(limit=50)
            self.chat.load_history(msgs)
        except Exception:
            pass
        # 11. 登录门禁
        if not self.account.current_username():
            self.chat.append(
                "<div style='color:#c00'>⚠ 未登录或账号未激活，请先登录已激活的账号。</div>"
            )
            while not self.account.current_username():
                try:
                    ok = self.show_login()
                except Exception:
                    traceback.print_exc()
                    ok = False
                if not ok:
                    r = QMessageBox.question(
                        self, "需要登录",
                        "未登录，是否重试？\n（点 No 退出程序）",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if r == QMessageBox.No:
                        QApplication.quit()
                        return
        # 12. 首次运行引导：模型还没配通时提示怎么配（延迟一点，先让窗口显示出来）
        try:
            from gui.onboarding_wizard import needs_onboarding, show_onboarding
            if needs_onboarding(self.trunk):
                QTimer.singleShot(400, lambda: show_onboarding(self.trunk, self))
        except Exception as e:
            try:
                self.trunk._log("首次引导检查失败: %s" % str(e)[:60])
            except Exception:
                pass

        # 13. 定时器
        self.last_user_msg = time.time()
        QTimer.singleShot(1500, self._persona_opening)
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._check_proactive)
        self._proactive_timer.start(10 * 60 * 1000)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(3 * 60 * 1000)

    def _do_login_flow(self):
        """异步登录流程：不阻塞Qt事件循环"""
        if self.account.current_username():
            return
        while not self.account.current_username():
            try:
                ok = self.show_login()
            except Exception:
                traceback.print_exc()
                ok = False
            if ok:
                return
            r = QMessageBox.question(
                self, "需要登录",
                "未登录，是否重试？\n（点 No 退出程序）",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.No:
                QApplication.quit()
                return
