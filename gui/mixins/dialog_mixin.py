# -*- coding: utf-8 -*-
"""对话框混入：所有窗口入口 + 后台任务启动"""
import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QWidget, QScrollArea, QMessageBox,
    QInputDialog, QFileDialog, QApplication, QLabel, QHBoxLayout,
    QPushButton,
)
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
        show_log_dialog(self, self._dlg, self.base,
                        self.export_logs, self.export_data, self.import_data)

    def plugin_dialog(self):
        from gui.plugin_dialog import show_plugin_dialog
        show_plugin_dialog(self, self._dlg, self.trunk,
                           self.show_mcp_market, self.show_components)

    def mcp_dialog(self):
        from gui.mcp_dialog import MCPDialog
        MCPDialog(self.trunk, self).show()

    def bot_dialog(self):
        from gui.bot_dialog import BotDialog
        BotDialog(self.trunk, self).show()

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
        # computer_dialog 不再传：设置里的"数据"标签连同那个按钮已移除
        show_settings_dialog(
            self, self._dlg, self.trunk, self.base,
            getattr(self, "ai_name", "小6"), getattr(self, "title", "小6智能体"),
            getattr(self, "model_btn", None), getattr(self, "_status_local", None), getattr(self, "_status_cloud", None),
            getattr(self, "chat", None), getattr(self, "input", None),
        )

    def center_dialog(self):
        from gui.center_dialog import show_center_dialog
        # 知识库 / 知识图谱 不再在这里露出。
        # 它俩只是"查看器"窗口，后台的 knowledge_graph / knowledge_qa /
        # vector_store 等模块照常运行、照常被对话链路调用（自动入图、检索、
        # RAG），摘掉入口不影响任何后台能力。
        # kb_dialog / graph_dialog 两个方法保留，要恢复入口加回一行即可。
        items = [
            ("🖥️", "电脑控制", "操作软件 / 文件 / 窗口 / 系统", self.computer_dialog),
            ("⚙️", "系统", "深度自检 / 备份 / 闭环 / 训练", self.sys_dialog),
            ("🧩", "插件", "安装 / 卸载 / 热加载模块", self.plugin_dialog),
            ("📋", "日志", "运行日志 / 错误 / 操作记录", self.log_dialog),
            ("🔌", "MCP市场", "可视化安装 MCP 服务器", self.mcp_dialog),
            ("🤖", "机器人", "企业微信/钉钉聊天机器人", self.bot_dialog),
            ("📜", "历史记录", "分页/搜索/导出全部聊天记录", self.history_dialog),
            ("🧭", "首次设置向导", "模型没配好、它不回话时打开这个", self.onboarding_dialog),
        ]
        show_center_dialog(self, self._dlg, items)

    def history_dialog(self):
        from gui.history_dialog import HistoryDialog
        HistoryDialog(self.trunk, self.account, self).show()

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
            except Exception:
                pass
            self.account.switch_user(username)
            self.chat.clear()
            self.chat.load_history(self.account.load_history())
        return show_login_dialog(self, self.trunk, self.base, on_success)

    def open_code_editor(self):
        try:
            from gui.code_editor_dialog import CodeEditorDialog
            CodeEditorDialog(self.trunk).show()
        except Exception as e:
            QMessageBox.warning(self, "编辑器", "打开失败: " + str(e)[:80])

    def send_last_code_to_editor(self):
        codes = getattr(self.chat, "_last_codes", None)
        if not codes:
            QMessageBox.information(self, "提示", "AI 还没给过代码")
            return
        try:
            from gui.code_editor_dialog import CodeEditorDialog
            d = CodeEditorDialog(self.trunk)
            d.set_code(codes[-1])
            d.show()
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
        res = self.trunk.call("file_upload", "read", path)
        self.chat.append("📄 文件: " + os.path.basename(path))
        self.chat.append("内容: " + str(res.get("text", ""))[:200])

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
        except Exception:
            pass
        if "云端" in item:
            self.model_btn.setText("🔄 模型:云端")
            self._status_local.setStyleSheet("color:#666;font-size:11px;padding:0 10px;")
            self._status_cloud.setStyleSheet("color:#0f0;font-size:11px;padding:0 10px;")
        else:
            self.model_btn.setText("🔄 模型:本地路由")
            self._status_local.setStyleSheet("color:#0f0;font-size:11px;padding:0 10px;")
            self._status_cloud.setStyleSheet("color:#0f0;font-size:11px;padding:0 10px;")

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

    def show_mcp_market(self):
        d = QDialog(self)
        d.setWindowTitle("🔌 MCP 市场")
        d.setMinimumSize(560, 400)
        l = QVBoxLayout(d)
        l.addWidget(QLabel("MCP Server 列表（点配置复制 JSON 到剪贴板）："))
        servers = [
            ("filesystem", "文件系统访问",
             '{"mcpServers":{"filesystem":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","/path/to/dir"]}}}'),
            ("fetch", "网页抓取",
             '{"mcpServers":{"fetch":{"command":"uvx","args":["mcp-server-fetch"]}}}'),
            ("git", "Git 仓库操作",
             '{"mcpServers":{"git":{"command":"uvx","args":["mcp-server-git","--repository","/path/to/repo"]}}}'),
        ]
        for name, desc, cfg in servers:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>{name}</b> {desc}"))
            row.addStretch(1)
            b = QPushButton("复制配置")
            def _cp(c=cfg):
                QApplication.clipboard().setText(c)
                QMessageBox.information(d, "已复制", "配置已复制到剪贴板")
            b.clicked.connect(_cp)
            row.addWidget(b)
            l.addLayout(row)
        l.addWidget(QPushButton("关闭", clicked=d.close))
        d.exec_()


