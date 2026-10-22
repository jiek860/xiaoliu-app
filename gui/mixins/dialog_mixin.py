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
from gui.workers import TaskWorker, LearnWorker, BgWorker


class DialogMixin:
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

    def graph_dialog(self):
        from gui.graph_dialog import show_graph_dialog
        show_graph_dialog(self, self._dlg, self.trunk)

    def kb_dialog(self):
        from gui.kb_dialog import show_kb_dialog
        show_kb_dialog(self, self._dlg, self.trunk, self._safe_stop_workers)

    def rag_dialog(self):
        from gui.rag_dialog import show_rag_dialog
        show_rag_dialog(self.trunk, self)

    def team_dialog(self):
        from gui.team_dialog import show_team_dialog
        show_team_dialog(self.trunk, self)

    def usage_dialog(self):
        from gui.usage_dialog import show_usage_dialog
        show_usage_dialog(self.trunk, self)

    def sys_dialog(self):
        from gui.system_dialog import show_system_dialog
        show_system_dialog(self)
        self._safe_stop_workers()

    def computer_dialog(self):
        from gui.computer_dialog import show_computer_dialog
        show_computer_dialog(self, self._dlg, self.trunk, self.chat,
                             self.set_dialog, self.kb_dialog)

    def log_dialog(self):
        from gui.log_dialog import show_log_dialog
        # export_logs / export_data 两个参数已去掉 —— 那两个按钮撤了
        # （它们是重复入口，能力已归到注册表的 crash_export / migrate_export，
        #  命令面板搜"导出"就能找到）。这里不再传自己的那份实现，
        # 免得同一件事有两个真相。
        return self._singleton_fn_dialog(
            "log_dialog",
            lambda: show_log_dialog(self, self._dlg, self.base,
                                    self.import_data))

    def plugin_dialog(self):
        from gui.plugin_dialog import show_plugin_dialog
        # 插件市场里那个「🔌 MCP」按钮也指向唯一的 MCP 面板
        # （以前指向 show_mcp_market，那是另一个只显示 JSON 的窗口）
        show_plugin_dialog(self, self._dlg, self.trunk,
                           self.mcp_dialog, self.show_components)

    def mcp_dialog(self):
        """打开 MCP 面板。重复点击复用同一个窗口，不会开出一堆。"""
        return self._singleton_dialog("mcp_dialog", "gui.mcp_dialog",
                                      "MCPDialog")

    def _singleton_fn_dialog(self, key, opener):
        """函数式开窗入口的单例复用。

        show_log_dialog / show_plugin_dialog 这类函数**不返回窗口**，
        但它们内部用 self._dlg(...) 构造，所以靠 _dlg 的缓存复用。
        这里只负责"不要重复调用 opener 造成重复构造"。
        """
        cache = getattr(self, "_fn_dialog_cache", None)
        if cache is None:
            cache = {}
            self._fn_dialog_cache = cache
        d = cache.get(key)
        if d is not None:
            try:
                d.show()
                d.raise_()
                d.activateWindow()
                return d
            except RuntimeError:
                cache.pop(key, None)
        result = opener()
        if result is not None:
            cache[key] = result
        return result

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
        d = SecurityCenterDialog(self.trunk, self)
        d.exec_()

    def task_center_dialog(self):
        from gui.task_center_dialog import TaskCenterDialog
        d = TaskCenterDialog(self.trunk, self)
        d.exec_()

    def show_feedback(self):
        from gui.feedback_dialog import FeedbackDialog
        FeedbackDialog(self.trunk, self).show()

    def show_tutorial(self):
        from gui.tutorial_dialog import show_tutorial_dialog
        show_tutorial_dialog(self)

    def show_components(self):
        from gui.components_dialog import show_components_dialog
        show_components_dialog(self, self.base, self._install_component)

    def set_dialog(self):
        from gui.settings_dialog import show_settings_dialog
        # 全容错：所有属性不存在就传None，绝对不报错
        # commands 就是原来"功能中心"里的那批入口，现已并入设置按用途分标签页。
        # 某个回调缺失时，设置里对应按钮会自动置灰。
        show_settings_dialog(
            self, self._dlg, self.trunk, self.base,
            getattr(self, "ai_name", "小6"),
            getattr(self, "model_btn", None), getattr(self, "_status_local", None), getattr(self, "_status_cloud", None),
            getattr(self, "chat", None), getattr(self, "input", None),
            self._panel_commands(),
        )

    # center_dialog() 已移除：它那 8 个入口全部并入上面的设置窗口，
    # 按用途分成了 工具 / 扩展 / 记录 / 系统 四个标签页。
    # 只留一个空壳"功能中心"反而会让人以为里面还有东西。
    # 知识库 / 知识图谱 两个查看器（kb_dialog / graph_dialog）按需求不在界面露出，
    # 后台的 knowledge_graph / knowledge_qa / vector_store 照常运行。

    def history_dialog(self):
        """历史记录窗口（签名不同：需要 account，所以单独处理单例）。"""
        cache = getattr(self, "_dialog_cache", None)
        if cache is None:
            cache = {}
            self._dialog_cache = cache
        d = cache.get("history_dialog")
        if d is not None:
            try:
                d.show()
                d.raise_()
                d.activateWindow()
                return d
            except RuntimeError:
                cache.pop("history_dialog", None)
        from gui.history_dialog import HistoryDialog
        d = HistoryDialog(self.trunk, self.account, self)
        cache["history_dialog"] = d
        d.show()
        return d

    # ---------------- 以下 9 个窗口原本是"孤儿" ----------------
    # 它们写好了、类也完整，但全项目没有任何地方能打开它们（实测过：
    # 12 个孤儿 GUI 文件里这 9 个都能正常构造）。这里给它们接上入口，
    # 按钮挂在「设置」对应的标签页里（见 gui/settings_dialog.py）。
    # 全部是同一种签名 (trunk, parent=None)，所以包一层就行。

    def _open_simple_dialog(self, modname, clsname, modal=True):
        """打开一个 (trunk, parent=None) 签名的窗口

        modal=True 走 exec_()（适合"看完就关"的）；
        否则走 show() 并留引用，免得窗口一闪就没（Python 侧被回收）。
        """
        try:
            mod = __import__("gui." + modname, fromlist=[clsname])
            cls = getattr(mod, clsname)
            w = cls(self.trunk, self)
        except Exception as e:
            QMessageBox.warning(self, "打开失败",
                                "%s 打不开：%s" % (clsname, str(e)[:120]))
            return None
        if modal:
            w.exec_()
        else:
            if not hasattr(self, "_keep_windows"):
                self._keep_windows = []
            self._keep_windows.append(w)
            w.show()
        return w

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

    def update_dialog(self):
        """检查更新 / 回滚 / 更新历史"""
        return self._open_simple_dialog("update_dialog", "UpdateDialog")

    def _panel_commands(self):
        """主窗口能打开的面板 —— 命令面板和设置窗口共用。"""
        from gui.panel_registry import build_panel_commands
        return build_panel_commands(self)

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
            return show_command_palette(self.trunk, self._panel_commands(), self)
        except Exception as e:
            QMessageBox.warning(self, "命令面板", "打不开：" + str(e)[:120])
            return None

    def module_tools_dialog(self):
        """🧰 实用工具 —— 兼容旧入口，现在转发到命令面板

        保留这个方法是因为设置里可能还有旧按钮指向它；
        它内部不再创建任何按钮（见 gui/module_tools_dialog.py 的说明）。
        """
        try:
            from gui.module_tools_dialog import ModuleToolsDialog
            w = ModuleToolsDialog(self.trunk, self)
            w.exec_()
            return w
        except Exception as e:
            QMessageBox.warning(self, "实用工具", "打不开：" + str(e)[:120])
            return None

    def module_map_dialog(self):
        """🕸️ 模块星图 —— 用系统浏览器打开

        页面本身在 docs/模块星图.html（随程序入库），数据由 trunk.export_module_map()
        每次启动写到 data/modules_map.js，页面用 ../data/modules_map.js 读它。
        之所以不在 Qt 里嵌：那张图是 ECharts 画的，塞进 QWebEngine 要多背一个
        几十 MB 的运行时，交给系统浏览器最省事。
        """
        import os
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
            ok = show_onboarding(self.trunk, self)
            QMessageBox.information(
                self, "首次设置向导",
                "配置完成，可以正常聊天了。" if ok else
                "还没配好：问它话可能不会有回复。\n"
                "缺什么上面写清楚了，随时可以再打开这个向导。")
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
            self.account.switch_user(username)
            self.chat.clear()
            self.chat.load_history(self.account.load_history())
        return show_login_dialog(self, self.trunk, self.base, on_success)

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
        # 原来这一句是 trunk.call("file_upload", "read", path)，里面藏着三个问题：
        #   ① file_upload 没有 read 方法（只有 read_file），调用只会返回
        #      「功能不可用」，文件内容永远是空的
        #   ② read_file(fname) 会把 fname 拼到 data/uploads 下面去找，
        #      传绝对路径必然"文件不存在"
        #   ③ 就算前两条都对了，它返回的键是"内容"不是这里读的"text"
        # 直接读用户刚选中并确认过的这个文件即可，顺带兼容 GBK 编码。
        try:
            try:
                text = open(path, encoding="utf-8").read()
            except UnicodeDecodeError:
                text = open(path, encoding="gbk", errors="ignore").read()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e)[:120])
            return
        self.chat.append("📄 文件: " + os.path.basename(path))
        self.chat.append("内容: " + text[:2000])

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

    def _bg_call(self, result, fn, label="处理"):
        result.setPlainText("▶ %s中，请稍候（后台执行，界面不卡）..." % label)
        w = BgWorker(fn)
        w.done.connect(lambda r: result.setPlainText(str(r)))
        self._bg_worker = w
        w.start()

    def _run_task_goal(self, result):
        goal, ok = QInputDialog.getText(
            self, "任务闭环",
            "输入要完成的目标（如：帮我写一个计算器脚本）:",
        )
        if not ok or not goal.strip():
            result.setPlainText("已取消")
            return
        result.setPlainText("▶ 任务闭环开始（拆步→子智能体执行→沙盒验证→评分），请稍候...")
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = []
            if r.get("ok"):
                lines.append("✔ 任务完成")
                lines.append("步骤数: %d | 评分: %s" % (r.get("步骤数", 0), r.get("评分", "?")))
                for it in (r.get("明细") or [])[:5]:
                    lines.append("- %s | %s | %s" % (
                        it.get("步骤", "")[:25], it.get("agent", "?"), it.get("验证", "")[:20]))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        self._task_worker = TaskWorker(self.trunk, goal.strip())
        self._task_worker.done.connect(lambda r: result.setPlainText(fmt(r)))
        self._task_worker.start()

    def _run_learn_one(self, result):
        result.setPlainText("▶ 学习闭环开始（搜索→提炼→入库），请稍候...")
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = []
            if r.get("ok"):
                lines.append("✔ 学习完成")
                lines.append("方向: %s" % r.get("方向", ""))
                lines.append("主题: %s" % r.get("主题", ""))
                lines.append("入库: %d 条" % r.get("入库条数", 0))
                lines.append("累计轮次: %s" % r.get("累计轮次", 0))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        self._learn_worker = LearnWorker(self.trunk)
        self._learn_worker.done.connect(lambda r: result.setPlainText(fmt(r)))
        self._learn_worker.start()

    def _export_backup_ui(self, result):
        dest = QFileDialog.getExistingDirectory(self, "选择导出目录（网盘/移动盘）")
        if not dest:
            result.setPlainText("已取消")
            return
        self._bg_call(result, lambda: self.trunk.call("backup", "export", dest), "导出备份")

    def _run_auto_update_ui(self, result):
        result.setPlainText("▶ 自更新闭环开始（取问题→建议→编程小匠→沙盒→确认→部署），请稍候...")
        def _fn():
            au = self.trunk.modules.get("auto_updater")
            if not au:
                self.trunk.call("auto_updater", "run")
                au = self.trunk.modules.get("auto_updater")
            if not au:
                return {"ok": False, "原因": "auto_updater 加载失败"}
            return au.run_auto_update()
        def fmt(r):
            if not isinstance(r, dict):
                return "返回异常: %s" % r
            lines = list(r.get("日志") or [])
            if r.get("ok"):
                lines.append("✔ 闭环完成 | 目标: %s | 备份: %s" % (
                    r.get("目标", ""), os.path.basename(r.get("备份", "?"))))
            else:
                lines.append("✖ 未完成: %s" % r.get("原因", "未知"))
            return "\n".join(lines)
        w = BgWorker(_fn)
        w.done.connect(lambda r: result.setPlainText(fmt(r) if isinstance(r, dict) else str(r)))
        self._au_worker = w
        w.start()

    def _module_button_clicked(self, module, action):
        if action.startswith("gui:"):
            fn = getattr(self, action[4:], None)
            if fn:
                fn()
                return
            QMessageBox.information(self, "模块按钮", "本地面板未找到: " + action)
            return
        r = self.trunk.call(module, action)
        if isinstance(r, dict):
            if r.get("ok") == False:
                err = r.get("error") or r.get("原因") or r.get("msg") or "未知错误"
                txt = f"「{module}」运行失败：\n{err[:200]}"
            else:
                txt = "\n".join("%s: %s" % (k, v) for k, v in r.items())
        else:
            txt = str(r)
        QMessageBox.information(self, module, txt[:2000])

    def _install_component(self, mod, pipname, status_label, btn):
        import sys as _sys
        btn.setEnabled(False)
        btn.setText("下载中…")
        opt_dir = os.path.join(self.base, "optional_libs")
        try:
            from pip._internal.cli.main import main as pip_main
            rc = pip_main([
                "install", "--quiet", "--disable-pip-version-check",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                "--target", opt_dir, pipname,
            ])
            if rc == 0:
                if opt_dir not in _sys.path:
                    _sys.path.insert(0, opt_dir)
                for m in list(_sys.modules.keys()):
                    if m == mod or m.startswith(mod + "."):
                        del _sys.modules[m]
                try:
                    __import__(mod)
                    status_label.setText("✅ 已装")
                    status_label.setStyleSheet("color:green;")
                    btn.setText("已安装")
                except ImportError as e:
                    status_label.setText("⚠ 装完但 import 失败: " + str(e)[:50])
            else:
                status_label.setText("⚠ 安装失败(code=%d)" % rc)
                btn.setText("重试")
        except Exception as e:
            status_label.setText("⚠ " + str(e)[:80])
            btn.setText("重试")
        finally:
            btn.setEnabled(True)

    # show_mcp_market() 已移除：它只是"显示几个 JSON 片段 + 复制"，属于
    # 另一个 MCP 窗口。现在所有 MCP 相关的东西（服务器管理 / 预置服务器 /
    # 配置参考）都在 gui/mcp_dialog.py 的 MCPDialog 里，通过 mcp_dialog() 打开。
