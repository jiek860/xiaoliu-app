# -*- coding: utf-8 -*-
"""主窗口 JarvisWindow —— 仅负责组装所有 Mixin 和初始化"""
import os
import json
import time
import threading
import traceback
from PyQt5.QtWidgets import (QMainWindow, QMessageBox, QApplication, QShortcut, QLabel)
from PyQt5.QtCore import pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QIcon, QKeySequence
from core.trunk import Trunk
from gui.mixins import (
    ChatMixin, DialogMixin, VoiceMixin, SystemMixin, LifecycleMixin,
    UIModeMixin, HistoryDraftMixin,
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
    HistoryDraftMixin,
    QMainWindow,
):
    confirmRequested = pyqtSignal(str, str)
    confirmScopeRequested = pyqtSignal(str, str)
    statusMessage = pyqtSignal(str)

    def __init__(self, startup=None, boot_signal=True):
        super().__init__()
        # 0. 启动计时（可选）：用来定位"哪一段慢了"
        self._startup = startup
        self._trunk_ready = False
        self._after_trunk_hooks = []
        if startup is not None:
            startup.mark("窗口对象创建")
        # 1. Trunk 初始化
        #    boot_signal=False 时只建窗口骨架，Trunk 由 _boot_trunk() 稍后填入。
        #    这是"秒开界面"的关键：先把空壳画出来，重活放到事件循环之后。
        if boot_signal:
            self._init_from_trunk(self._boot_trunk())
        else:
            # 延迟启动：先只装"不依赖 trunk"的骨架，等 BootController 补上。
            # 明确置 None：别的代码/测试会用 `w.trunk is None` 判断"还没就绪"。
            self.trunk = None
            self._init_skeleton()
    def _boot_trunk(self):
        """创建 trunk（后台线程会调它，见 start_background_boot）。"""
        import time as _t
        t0 = _t.perf_counter()
        trunk = Trunk()
        if self._startup is not None:
            self._startup.mark("Trunk 初始化完成")
        try:
            trunk.perf.record("startup.trunk_init", _t.perf_counter() - t0)
        except Exception as e:
            _x6_swallowed(__name__, e, "best-effort fallback")
        return trunk

    def _init_skeleton(self):
        """不依赖 trunk 的最小骨架：窗口属性 + 图标 + 最小尺寸 + 主题。

        这样窗口能立刻显示出来；依赖 trunk 的 UI/账号/定时器由
        BootController 在事件循环之后补上。
        """
        self.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.setWindowTitle("✨ 小6智能体")
        _ico = os.path.join(self.base, "app.ico")
        if os.path.exists(_ico):
            self.setWindowIcon(QIcon(_ico))
        self.setMinimumSize(1100, 750)
        try:
            from gui.style import STYLE
            self.setStyleSheet(STYLE)
        except Exception as e:  # 静默是故意的 - 骨架样式失败不该拦住启动
            _x6_swallowed(__name__, e, "best-effort fallback")
        self._boot_placeholder = QLabel("正在启动…", self)
        self._boot_placeholder.setAlignment(Qt.AlignCenter)
        self._boot_placeholder.setStyleSheet(
            "color:#64748b;font-size:14px;background:#f8fafc;")
        self.setCentralWidget(self._boot_placeholder)
        self._confirm_evt = threading.Event()
        self._confirm_result = {"ok": False}
        self._after_trunk_hooks = []

    def _init_from_trunk(self, trunk):
        """把依赖 trunk 的部分集中初始化（骨架和全量启动共用这条路径）。"""
        self.trunk = trunk
        self.base = getattr(trunk, "base", None) or \
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
        # 草稿自动保存：输入变化后节流落盘，重启可恢复
        self._setup_draft_autosave()
        # 8.6 Agent 产物回收：data/agent_runs 只保留最近 40 个 / 7 天，
        #     事件文件裁到 5000 行；放后台线程，不拖慢启动。
        try:
            from core.agent_artifacts import maybe_cleanup
            threading.Thread(target=maybe_cleanup, args=(self.base,),
                             daemon=True).start()
        except Exception as e:  # 静默是故意的 - 回收失败不影响启动
            _x6_swallowed(__name__, e, "best-effort fallback")
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

        # 9.0 按已保存的配置回填"本地/云端"指示灯。
        # ⚠️ 修复：以前只有 switch_model() 内部会改灯的颜色，
        #    所以**重启后**指示灯停在 build_ui 的初始值（本地绿、云端灰），
        #    用户上次选的"云端模型"看起来像没保存。现在启动即回读。
        try:
            from gui.status_lights import paint_from_config
            paint_from_config(self)
        except Exception as e:  # 静默是故意的 - 指示灯回填失败不阻断启动
            _x6_swallowed(__name__, e, "best-effort fallback")

        # ===== 协议确认 =====
        # ⚠️ 以前在 __init__ 里同步 exec_()，于是启动瞬间会**连着弹三个框**：
        #    协议 -> 登录 -> 首次向导（登录框里还会再查一次协议）。
        #    用户感受就是"一打开就一堆弹窗"。现在改成：
        #      · 协议确认排到窗口显示之后（_do_login_flow 里统一编排）
        #      · 一次只允许一个模态框，其余等前一个关掉再弹
        try:
            from core.agreement import Agreement
            self._agreement = Agreement(self.trunk)
            self._agreement_pending = bool(self._agreement.need_show())
        except Exception as e:  # 静默是故意的
            self._agreement = None
            self._agreement_pending = False
            try:
                self.trunk._log("协议检查失败: %s" % str(e)[:60])
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
        if not getattr(self, "_agreement_pending", False):
            self._agreement_confirmed = True

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
        # 10. 加载历史首屏 + 恢复当前会话草稿
        try:
            self._reload_chat_history()
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

        # 15. Esc 停止回复：回复过程中随时可以打断，已收到的内容保留。
        try:
            sc_stop = QShortcut(QKeySequence("Esc"), self)
            sc_stop.activated.connect(self.stop_reply)
            self._stop_shortcut = sc_stop     # 留引用，否则会被回收
        except Exception as e:  # 静默是故意的
            try:
                from core.logger import get_logger
                get_logger().warn("Esc 停止回复快捷键没装上: %s: %s"
                                  % (type(e).__name__, str(e)[:80]))
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def _do_login_flow(self):
        """窗口显示后的**串行**引导：协议 -> 登录 -> 首次配置向导。

        为什么改成串行
        --------------
        以前三段各自 `exec_()`：协议在 __init__ 里弹、登录在 singleShot(0) 里弹、
        向导又 singleShot(400) 里弹。三者时间上重叠，会出现"协议还盖着，
        登录框已经起来了，关掉又冒出向导"，看起来像一堆弹窗互相抢焦点。
        现在改成一条链：每一步返回后，才决定要不要弹下一步。
        """
        if os.environ.get("X6_DISABLE_LOGIN_PROMPT") == "1":
            self._after_agreement_login()
            return
        # 启动期确认"只问一次"：协议同意过就跳过（见 core/startup_consent.py）
        base = getattr(self, "base", ".")
        try:
            from core import startup_consent as _sc
            _agreed_before = _sc.is_granted(base, "agreement")
        except Exception:  # 静默是故意的 - 记录读不到就按"没同意"处理
            _sc = None
            _agreed_before = False
        if _agreed_before and not getattr(self, "_agreement_pending", False):
            self._agreement_pending = False
        elif getattr(self, "_agreement_pending", False):
            if not self._confirm_agreement():
                QApplication.quit()
                return
            if _sc is not None:
                _sc.grant(base, "agreement", "用户在启动时同意协议")
        self._after_agreement_login()

    def _confirm_agreement(self):
        """弹一次协议确认；同意返回 True。"""
        try:
            from gui.agreement_dialog import AgreementDialog
            dlg = AgreementDialog(self.trunk, self)
            dlg.exec_()
            if dlg.agreed:
                self._agreement_pending = False
                self._agreement_confirmed = True
                return True
            QMessageBox.information(self, "退出", "您未同意协议，程序将退出。")
            return False
        except Exception as e:  # 静默是故意的 - 协议框坏了不该让程序打不开
            try:
                self.trunk._log("协议确认失败: %s" % str(e)[:60])
            except Exception:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")
            # 打不开协议框就当作已确认，避免把用户锁死在启动阶段
            self._agreement_pending = False
            return True

    def _after_agreement_login(self):
        """协议之后：登录 -> 首次向导，两个框绝不重叠。"""
        if os.environ.get("X6_DISABLE_LOGIN_PROMPT") == "1":
            return
        # 先尝试恢复上次登录（auth.restore_session 会重新验签/查过期）
        restored = {"ok": False}
        if not self.account.current_username():
            try:
                restored = self.account.try_restore_login()
            except Exception:  # 静默是故意的 - 恢复失败就走正常登录
                restored = {"ok": False}
            if restored.get("ok"):
                try:
                    self.trunk._log("已自动恢复登录: %s" % restored.get("user"))
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "best-effort fallback")
                # 启动时可能先按 guest 渲染过历史，恢复登录后重建
                self._reload_chat_history()
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
        if os.environ.get("X6_DISABLE_LOGIN_PROMPT") == "1":
            # 测试/无人值守：不弹任何模态框
            return
        try:
            from gui.onboarding_wizard import needs_onboarding, show_onboarding
            if needs_onboarding(self.trunk):
                show_onboarding(self.trunk, self)
                # 刚配好模型，空状态卡还写着"模型还没配置好"就自相矛盾了：
                # 关闭向导后立刻按最新配置重算引导卡（不重算要等第一次聊天）。
                try:
                    self._refresh_guidance()
                except Exception as e:  # 静默是故意的
                    _x6_swallowed(__name__, e, "refresh guidance after onboarding")
                try:
                    from core import startup_consent as _sc
                    _sc.grant(getattr(self, "base", "."), "onboarding",
                              "用户走完首次配置向导")
                except Exception as e:  # 静默是故意的 - 记录失败不影响引导结果
                    _x6_swallowed(__name__, e, "best-effort fallback")
        except Exception as e:  # 静默是故意的
            try:
                self.trunk._log("首次引导检查失败: %s" % str(e)[:60])
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "best-effort fallback")

    def closeEvent(self, event):
        """关闭窗口时停掉后台定时器与线程。

        修复的真实问题（2026-10-22）：本类原来**没有 closeEvent**，
        于是 3 个 QTimer（活动徽章 1s / 主动关怀 10min / 状态刷新 3min）
        在窗口关闭后仍在跑，后台线程数从 7 不下降。
        这会让"关掉界面但程序没退干净"或退出时卡住。
        """
        # 关窗前把未发送的输入落盘，下次启动还能接着写
        self._save_draft_now()
        # 先关掉所有子窗口：任务中心/活动中心会注销运行时订阅、停掉定时器。
        # 不关就直接销毁主窗，后台线程仍会往已释放的窗口发信号（退出崩溃）。
        try:
            from PyQt5.QtWidgets import QDialog
            for dlg in self.findChildren(QDialog):
                try:
                    if dlg.isVisible():
                        dlg.close()
                except Exception as e:  # 静默是故意的 - 单个窗口关不掉不影响退出
                    _x6_swallowed(__name__, e, "close child dialog")
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "close child dialogs")
        for name in ("_activity_timer", "_proactive_timer", "_status_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception as e:  # 静默是故意的 - 停不掉也要继续关窗
                    _x6_swallowed(__name__, e, "best-effort fallback")
        # 通知 trunk 收尾（停插件 worker / MCP 子进程 / 后台线程）
        try:
            stopper = getattr(self.trunk, "shutdown", None)
            if callable(stopper):
                stopper()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "best-effort fallback")
        super().closeEvent(event)
