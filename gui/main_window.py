# -*- coding: utf-8 -*-
"""主窗口 JarvisWindow —— 仅负责组装所有 Mixin 和初始化"""
import os
import json
import time
import threading
import traceback
from PyQt5.QtWidgets import (QMainWindow, QMessageBox, QApplication, QShortcut)
from PyQt5.QtCore import pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from core.trunk import Trunk
from gui.mixins import (
    ChatMixin, DialogMixin, VoiceMixin, SystemMixin, LifecycleMixin,
    UIModeMixin,
)
# 样式表只有 gui/style.py 一份。
# 这里原来粘了一份一模一样的副本，两边都得改 —— 正是"改了一个忘另一个"的经典坑。
# 而且那份副本里的 padding:10px 会让 32px 高的按钮只剩 10px 放字（见 module_tools_dialog）。
from gui.style import STYLE

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None



class JarvisWindow(
    ChatMixin,
    DialogMixin,
    VoiceMixin,
    SystemMixin,
    LifecycleMixin,
    UIModeMixin,
    QMainWindow,
):
    confirmRequested = pyqtSignal(str, str)
    confirmScopeRequested = pyqtSignal(str, str)
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
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 4. 危险操作确认信号
        self._confirm_evt = threading.Event()
        self._confirm_result = {"ok": False}
        self.confirmRequested.connect(self._ask_confirm)
        self.confirmScopeRequested.connect(self._ask_confirm_scope)
        self.trunk.confirm_cb = self._confirm_wait
        self.trunk.confirm_scope_cb = self._confirm_scope_wait
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
        from gui.theme_manager import ThemeManager
        from gui.window_state import WindowStateManager
        self.theme_manager = ThemeManager(self.base)
        self.window_state = WindowStateManager(self.base)
        self.theme_manager.apply_to(self)
        # 7. 账号管理器（必须在build_ui之前）
        from gui.account import AccountManager
        self.account = AccountManager(self.trunk, self.base)
        # 7.5 兼容旧接口
        self.chat_store = self.account.chat_store
        self._chat_username = self.account.username
        self._chat_session = self.account.session
        # 8. UI 模式 + 引导状态（必须在 build_ui 前初始化，布局按模式显隐）
        from gui.ui_mode import UIModeManager
        from gui.guidance import GuidanceEngine
        self.ui_mode = UIModeManager(
            self.base, self.trunk.config, self.trunk.save_config)
        self.ui_mode_value = self.ui_mode.mode
        self.guidance = GuidanceEngine(self.base, self.trunk)
        # 8.5 构建 UI
        from gui.build_ui import build_ui
        build_ui(self)
        try:
            self.chat.textChanged.connect(self._update_empty_state)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        try:
            self._refresh_guidance()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 活动中心状态：每秒只更新一个数量标签，不轮询业务表
        try:
            self._refresh_activity_badge()
            self._activity_timer = QTimer(self)
            self._activity_timer.timeout.connect(self._refresh_activity_badge)
            self._activity_timer.start(1000)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

        try:
            self.window_state.restore(self)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")

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
        except Exception as e:  # 静默是故意的
            try:
                self.trunk._log("协议确认失败: %s" % str(e)[:60])
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

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
                    except Exception as e:  # 静默是故意的
                        _x6_swallowed(__name__, e, "best-effort fallback")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 10. 加载历史
        try:
            msgs = self.account.load_history(limit=50)
            self.chat.load_history(msgs)
            self._refresh_guidance()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        # 11. 登录门禁：改成窗口显示之后再走（见 _do_login_flow）
        #     这里原来是个阻塞 while，窗口要等登录完才 show() —— 用户只看到一个
        #     孤零零的登录框浮在空桌面上，后面什么都没有。现在主界面先画出来，
        #     登录框浮在它上面（show_login 内部是模态 exec_，事件循环照常转）。
        if not self.account.current_username():
            self.chat.append(
                "<div style='color:#c00'>⚠ 未登录或账号未激活，请先登录已激活的账号。</div>"
            )
        QTimer.singleShot(0, self._do_login_flow)

        # 12. 首次运行引导挪进 _do_login_flow 末尾 —— 否则它会盖在登录框上

        # 13. 定时器
        self.last_user_msg = time.time()
        QTimer.singleShot(1500, self._persona_opening)
        self._proactive_timer = QTimer(self)
        self._proactive_timer.timeout.connect(self._check_proactive)
        self._proactive_timer.start(10 * 60 * 1000)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(3 * 60 * 1000)

        # 14. 命令面板快捷键 Ctrl+K
        #     这是"撤按钮"的配套：能力不再各配一个常驻按钮，改成按需搜索。
        #     用 ApplicationShortcut 让它在任何子窗口聚焦时也能唤起。
        try:
            _sc_text = self.trunk.config.get(
                "shortcut_command_palette", "Ctrl+K") or "Ctrl+K"
            sc = QShortcut(QKeySequence(_sc_text), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self.command_palette)
            self._cmd_shortcut = sc          # 留引用，否则会被回收
        # ⚠️ 原来是 `except Exception:  # 静默是故意的 pass` —— 那让"快捷键没装上"变成
        #    彻底的静默失败（2026-10-14 改）。
        #    实测踩到：CI 上 `test_main_window_assembles` 报
        #    "Ctrl+K 快捷键没装上"，而本地一直是绿的 ——
        #    因为异常被这里吞了，**本地/CI 的差别一个字都看不到**。
        #    现在至少写一条日志，下次能直接看到原因。
        except Exception as e:  # 静默是故意的
            try:
                from core.logger import get_logger
                get_logger().warn("Ctrl+K 快捷键没装上（功能仍可用，"
                                  "但没有快捷键）: %s: %s"
                                  % (type(e).__name__, str(e)[:80]))
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _do_login_flow(self):
        """窗口显示后再走登录门禁（原来在 __init__ 里阻塞，窗口得等登录完才出现）"""
        try:
            while not self.account.current_username():
                try:
                    ok = self.show_login()
                except Exception:  # 静默是故意的
                    traceback.print_exc()
                    ok = False
                if ok:
                    break
                r = QMessageBox.question(
                    self, "需要登录",
                    "未登录，是否重试？\n（点 No 退出程序）",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if r == QMessageBox.No:
                    QApplication.quit()
                    return
        finally:
            # 登录过了（或本来就在登录态）才提示首次配置
            QTimer.singleShot(400, self._maybe_onboarding)

    def _maybe_onboarding(self):
        """首次运行引导：模型还没配通时提示怎么配"""
        if not self.account.current_username():
            return
        try:
            from gui.onboarding_wizard import needs_onboarding, show_onboarding
            if needs_onboarding(self.trunk):
                show_onboarding(self.trunk, self)
        except Exception as e:  # 静默是故意的
            try:
                self.trunk._log("首次引导检查失败: %s" % str(e)[:60])
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
