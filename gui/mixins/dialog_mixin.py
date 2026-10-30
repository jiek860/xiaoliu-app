# -*- coding: utf-8 -*-
"""对话框混入：所有窗口入口 + 后台任务启动"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

import os
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QWidget, QScrollArea, QMessageBox, QInputDialog, QFileDialog
from PyQt5.QtCore import Qt
from gui.mixins.background_tasks_mixin import BackgroundTaskMixin


class DialogMixin(BackgroundTaskMixin):
    """对话框相关方法"""
    def _dlg(self, title, w=500, h=600):
        d = QDialog(self)
        d.setWindowTitle(title)
        d.setFixedSize(w, h)
        scroll = QScrollArea(d)
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        scroll.setWidget(inner)
        ml = QVBoxLayout(d)
        ml.addWidget(scroll)
        return d, lay

    # ---- 单窗口入口：点多少次都只出一个（实现见 gui/chrome.py） ----
    # 非模态走 singleton_window 缓存复用；模态走 run_modal_once 重入守卫。
    # 真实问题：任务中心 / 活动中心 / 命令面板 / 意见反馈用 .show()，
    # 每点一次 new 一个；链接双击也会把两次调用排进事件队列。
    def _run_modal_once(self, key, opener):
        """模态窗口只允许一个：正在打开时重复调用直接返回 None。"""
        from gui.chrome import run_modal_once
        return run_modal_once(self, key, opener)

    def _singleton_window(self, key, factory, focus=None):
        """非模态窗口单例：已开着就前置；用户关掉后才允许重建。"""
        from gui.chrome import singleton_window
        return singleton_window(self, key, factory, focus)

    def graph_dialog(self):
        from gui.graph_dialog import show_graph_dialog
        return self._run_modal_once(
            "graph_dialog",
            lambda: show_graph_dialog(self, self._dlg, self.trunk))

    def kb_dialog(self):
        from gui.kb_dialog import show_kb_dialog
        return self._run_modal_once(
            "kb_dialog",
            lambda: show_kb_dialog(self, self._dlg, self.trunk,
                                   self._safe_stop_workers))

    def rag_dialog(self):
        from gui.rag_dialog import show_rag_dialog
        return self._run_modal_once(
            "rag_dialog", lambda: show_rag_dialog(self.trunk, self))

    def team_dialog(self):
        from gui.team_dialog import show_team_dialog
        return self._run_modal_once(
            "team_dialog", lambda: show_team_dialog(self.trunk, self))

    def usage_dialog(self):
        from gui.usage_dialog import show_usage_dialog
        return self._run_modal_once(
            "usage_dialog", lambda: show_usage_dialog(self.trunk, self))

    def sys_dialog(self):
        from gui.system_dialog import show_system_dialog

        def _make():
            w = show_system_dialog(self)
            self._safe_stop_workers()
            return w

        return self._singleton_window("sys_dialog", _make)

    def computer_dialog(self):
        from gui.computer_dialog import show_computer_dialog
        return self._singleton_window(
            "computer_dialog",
            lambda: show_computer_dialog(
                self, self._dlg, self.trunk, self.chat,
                self.set_dialog, self.kb_dialog))

    def log_dialog(self):
        from gui.log_dialog import show_log_dialog
        # export_logs / export_data 两个参数已去掉 —— 那两个按钮撤了
        # （它们是重复入口，能力已归到注册表的 crash_export / migrate_export，
        #  命令面板搜"导出"就能找到）。这里不再传自己的那份实现，
        # 免得同一件事有两个真相。
        return self._run_modal_once(
            "log_dialog",
            lambda: show_log_dialog(self, self._dlg, self.base,
                                    self.import_data))

    def plugin_dialog(self):
        from gui.plugin_dialog import show_plugin_dialog
        # 插件市场里那个「🔌 MCP」按钮也指向唯一的 MCP 面板
        # （以前指向 show_mcp_market，那是另一个只显示 JSON 的窗口）
        return self._run_modal_once(
            "plugin_dialog",
            lambda: show_plugin_dialog(
                self, self._dlg, self.trunk,
                self.mcp_dialog, self.show_components))

    def mcp_dialog(self):
        """打开 MCP 面板。重复点击切到同一个标签页，不再单开窗口。"""
        from gui.chrome import open_panel
        return open_panel(self, "mcp_dialog", "🔌 MCP",
                          "gui.mcp_dialog", "MCPDialog")

    def _singleton_dialog(self, key, module, cls_name):
        """按 key 复用窗口：已存在就 raise+activate，否则新建。

        修复的真实问题（2026-10-22）：连点三次 MCP 按钮会开出 3 个窗口，
        用户得一个个关。所有 _dialog 入口都应走这里。
        """
        try:
            import importlib
            cls = getattr(importlib.import_module(module), cls_name)
        except Exception as e:  # 静默是故意的 - 模块坏了就提示而不是崩
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "打开失败", str(e)[:160])
            return None
        cache = getattr(self, "_dialog_cache", None)
        if cache is None:
            cache = {}
            self._dialog_cache = cache
        d = cache.get(key)
        if d is not None:
            try:
                d.show()
                d.raise_()
                d.activateWindow()
                return d
            except RuntimeError:
                # 底层 C++ 对象已销毁（用户关掉了），重建
                cache.pop(key, None)
        try:
            d = cls(self.trunk, self)
        except TypeError:
            d = cls(self.trunk)
        cache[key] = d
        d.show()
        d.raise_()
        return d

    def bot_dialog(self):
        return self._singleton_dialog("bot_dialog", "gui.bot_dialog", "BotDialog")

    def security_center_dialog(self):
        from gui.security_center_dialog import SecurityCenterDialog
        return self._run_modal_once(
            "security_center",
            lambda: SecurityCenterDialog(self.trunk, self).exec_())

    def task_center_dialog(self):
        # 兼容旧命令面板入口；统一走任务中心的单窗口实现
        return self.open_task_center()

    def show_feedback(self):
        from gui.feedback_dialog import FeedbackDialog
        return self._singleton_window(
            "feedback", lambda: FeedbackDialog(self.trunk, self))

    def show_tutorial(self):
        from gui.tutorial_dialog import show_tutorial_dialog
        return self._run_modal_once(
            "tutorial", lambda: show_tutorial_dialog(self))

    def show_components(self):
        from gui.components_dialog import show_components_dialog
        return self._run_modal_once(
            "components",
            lambda: show_components_dialog(
                self, self.base, self._install_component))

    # center_dialog() 已移除：它那 8 个入口全部并入上面的设置窗口，
    # 按用途分成了 工具 / 扩展 / 记录 / 系统 四个标签页。
    # 只留一个空壳"功能中心"反而会让人以为里面还有东西。
    # 知识库 / 知识图谱 两个查看器（kb_dialog / graph_dialog）按需求不在界面露出，
    # 后台的 knowledge_graph / knowledge_qa / vector_store 照常运行。

    def history_dialog(self):
        """历史记录窗口（签名不同：需要 account，所以单独给 factory）。"""
        from gui.history_dialog import HistoryDialog
        return self._singleton_window(
            "history_dialog",
            lambda: HistoryDialog(self.trunk, self.account, self))

    # ---------------- 以下 9 个窗口原本是"孤儿" ----------------
    # 它们写好了、类也完整，但全项目没有任何地方能打开它们（实测过：
    # 12 个孤儿 GUI 文件里这 9 个都能正常构造）。这里给它们接上入口，
    # 按钮挂在「设置」对应的标签页里（见 gui/settings_dialog.py）。
    # 全部是同一种签名 (trunk, parent=None)，所以包一层就行。

    def _open_simple_dialog(self, modname, clsname, modal=True):
        """打开一个 (trunk, parent=None) 签名的窗口

        modal=True 走 exec_()（适合"看完就关"的）；
        否则走 show() 并复用同一个窗口，免得连点叠窗。
        """
        def _make():
            try:
                mod = __import__("gui." + modname, fromlist=[clsname])
                cls = getattr(mod, clsname)
                return cls(self.trunk, self)
            except Exception as e:
                QMessageBox.warning(self, "打开失败",
                                    "%s 打不开：%s" % (clsname, str(e)[:120]))
                return None

        key = "simple:" + modname
        if not modal:
            return self._singleton_window(key, _make)

        def _open():
            w = _make()
            if w is not None:
                w.exec_()
            return w

        return self._run_modal_once(key, _open)

    def model_manager_dialog(self):
        """本地模型管理：列出 / 下载 / 删除 Ollama 模型"""
        return self._open_simple_dialog("model_manager_dialog", "ModelManagerDialog")

    def voice_chat_dialog(self):
        """语音实时对话：VAD 静音检测、可随时打断、连续多轮"""
        return self._open_simple_dialog("voice_chat_dialog", "VoiceChatDialog")

    def memory_view_dialog(self):
        """记忆可视化：时间线 / 图谱 / 搜索 / 编辑"""
        return self._open_simple_dialog("memory_view_dialog", "MemoryViewDialog")

    def stats_dialog(self):
        """数据统计报表"""
        return self._open_simple_dialog("stats_dialog", "StatsDialog")

    def tools_dialog(self):
        """日历 + 待办 + 笔记"""
        return self._open_simple_dialog("tools_dialog", "ToolsDialog")

    def search_dialog(self):
        """消息搜索：全局搜索所有会话"""
        return self._open_simple_dialog("search_dialog", "SearchDialog")

    def research_dialog(self):
        """深度研究：多跳联网研究，带引用报告"""
        return self._open_simple_dialog("research_dialog", "ResearchDialog")

    def update_dialog(self):
        """检查更新 / 回滚 / 更新历史"""
        return self._open_simple_dialog("update_dialog", "UpdateDialog")

    def _panel_commands(self):
        """主窗口能打开的面板 —— 命令面板和设置窗口共用。"""
        from gui.panel_registry import build_panel_commands
        return build_panel_commands(self)

    def chat_topics_dialog(self):
        """🕘 聊天话题时间线：按话题跳回本轮会话里的原消息。"""
        try:
            from gui.chat_timeline import open_timeline
            d = self._singleton_window(
                "chat_timeline", lambda: open_timeline(self))
            return d
        except Exception as e:
            QMessageBox.warning(self, "话题时间线", "打不开：" + str(e)[:120])
            return None

    def command_palette(self):
        """⌘ 命令面板（Ctrl+K）—— 能力/面板/工具的统一搜索入口

        它**取代**了原"实用工具"面板那 24 个按钮：那 24 条能力里 23 条"说一句"
        就能用，做成常驻按钮既占地方（一个人占了 GUI 114 处控件里的 24 处）
        又要手工维护（手写 ACTIONS 表，模块改了不会自动跟）。
        现在数据来自 core/module_caps 能力注册表 —— 模块声明 TOOLS 就自动进来。

        回滚：git revert 这次提交即可（旧实现完整留在 git 历史里），
        ACTIONS 那 24 条也没丢，已全部变成注册表里的能力声明。
        """
        try:
            from gui.command_palette import show_command_palette
            d = self._singleton_window(
                "command_palette",
                lambda: show_command_palette(
                    self.trunk, self._panel_commands(), self))
            if d is not None:
                try:
                    d.search.setFocus()
                except Exception as e:  # 静默是故意的 - 聚焦失败不影响面板
                    _x6_swallowed(__name__, e, "focus command palette")
            return d
        except Exception as e:
            QMessageBox.warning(self, "命令面板", "打不开：" + str(e)[:120])
            return None

    def module_tools_dialog(self):
        """🧰 实用工具 —— 兼容旧入口，现在转发到命令面板

        保留这个方法是因为设置里可能还有旧按钮指向它；
        它内部不再创建任何按钮（见 gui/module_tools_dialog.py 的说明）。
        直接转命令面板：两个入口开同一个窗口，不会叠出两份。
        """
        return self.command_palette()

    def module_map_dialog(self):
        """🕸️ 模块星图 —— 用系统浏览器打开

        页面本身在 docs/模块星图.html（随程序入库），数据由 trunk.export_module_map()
        每次启动写到 data/modules_map.js，页面用 ../data/modules_map.js 读它。
        之所以不在 Qt 里嵌：那张图是 ECharts 画的，塞进 QWebEngine 要多背一个
        几十 MB 的运行时，交给系统浏览器最省事。
        """
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        html = os.path.join(self.base, "docs", "模块星图.html")
        if not os.path.exists(html):
            QMessageBox.information(self, "模块星图", "找不到星图页面：\n" + html)
            return None
        # 顺手重导一次，避免看到的是上一次启动的旧图
        try:
            self.trunk.export_module_map()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(html))
        return None

    def pet_dialog(self):
        """桌面悬浮窗（桌宠）—— 非模态，可以一直开着

        它是常驻的小窗口，不是"打开-关闭"的对话框，所以：
          · show() 而不是 exec_()（不然会把主界面卡住）
          · 已经开着就再点一次收起来（当开关用）
        """
        try:
            w = getattr(self, "_desktop_pet", None)
            if w is not None:
                if w.isVisible():
                    w.hide()
                    return None
                w.show()
                return w
            from gui.desktop_pet import DesktopPet
            w = DesktopPet(self.trunk, self)
            self._desktop_pet = w
            w.show()
            return w
        except Exception as e:
            QMessageBox.warning(self, "桌宠", "打不开：" + str(e)[:120])
            return None

    def onboarding_dialog(self):
        """重新打开首次设置向导（模型没配好时随时可用）"""
        try:
            from gui.onboarding_wizard import show_onboarding

            def _open():
                ok = show_onboarding(self.trunk, self)
                QMessageBox.information(
                    self, "首次设置向导",
                    "配置完成，可以正常聊天了。" if ok else
                    "还没配好：问它话可能不会有回复。\n"
                    "缺什么上面写清楚了，随时可以再打开这个向导。")
                return ok

            return self._run_modal_once("onboarding", _open)
        except Exception as e:
            QMessageBox.warning(self, "引导", "打开失败: " + str(e)[:100])

    def show_login(self):
        from gui.login_dialog import show_login_dialog

        def on_success(username):
            try:
                self.login_btn_sb.setText("🔑 " + str(username))
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            self._save_draft_now()
            self.account.switch_user(username)
            self._reload_chat_history()
        return self._run_modal_once(
            "login",
            lambda: show_login_dialog(self, self.trunk, self.base,
                                      on_success))

    def open_code_editor(self):
        try:
            self.open_workbench()
        except Exception as e:
            QMessageBox.warning(self, "编辑器", "打开失败: " + str(e)[:80])

    def send_last_code_to_editor(self):
        codes = getattr(self.chat, "_last_codes", None)
        if not codes:
            QMessageBox.information(self, "提示", "AI 还没给过代码")
            return
        try:
            wb = self.open_workbench()
            editor = getattr(wb, "_editor", None) if wb is not None else None
            if editor is None or not hasattr(editor, "set_code"):
                return
            # 工作台里的编辑器已内嵌，不需要 show()，只需把代码塞进新标签
            editor.set_code(codes[-1])
        except Exception as e:
            QMessageBox.warning(self, "编辑器", str(e)[:80])

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "所有文件 (*.*)")
        if not path:
            return
        r = QMessageBox.question(self, "确认", "要读取这个文件吗?\n" + path,
                                 QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        # 统一走 chat_input_ext：PDF/Word/Excel/PPT/MD/HTML 都交给
        # core.document_parser 解析，结果放进输入框，发送时随消息给模型。
        # 以前这里只 open().read()，PDF/Word 直接报 UnicodeDecodeError。
        try:
            from gui.chat_input_ext import attach_document
            attach_document(self, path)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e)[:120])

    def switch_model(self):
        items = ["本地路由", "云端模型"]
        item, ok = QInputDialog.getItem(
            self, "切换模型",
            "本地路由：问候→小模型，日常/群聊→7B，带图/复杂→VL，本地异常时云端兜底\n"
            "云端模型：只连云端",
            items, 0, False,
        )
        if not ok:
            return
        self.trunk.config["model_mode"] = item
        self.trunk.save_config()
        try:
            self.trunk.modules["llm"].reload_config()
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
        # 统一走 status_lights：之前本地/云端两个灯**同时**变绿是 bug。
        try:
            from gui.status_lights import paint
            paint(item, getattr(self, "_status_local", None),
                  getattr(self, "_status_cloud", None),
                  getattr(self, "model_btn", None),
                  getattr(self, "model_status_label", None))
        except Exception:  # 静默是故意的 - 指示灯刷新失败不影响模型切换
            pass

    # _bg_call / _run_task_goal / _run_learn_one / _export_backup_ui /
    # _run_auto_update_ui / _module_button_clicked / _install_component
    # 已搬到 gui/mixins/background_tasks_mixin.py（本文件接近 600 行上限），
    # 由 BackgroundTaskMixin 提供，方法名不变。

    # show_mcp_market() 已移除：它只是"显示几个 JSON 片段 + 复制"，属于
    # 另一个 MCP 窗口。现在所有 MCP 相关的东西（服务器管理 / 预置服务器 /
    # 配置参考）都在 gui/mcp_dialog.py 的 MCPDialog 里，通过 mcp_dialog() 打开。