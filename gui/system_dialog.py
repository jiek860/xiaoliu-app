# -*- coding: utf-8 -*-
"""系统窗口 v2.0 - 标签页卡片式（仿设置窗口）"""
try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

from PyQt5.QtWidgets import QVBoxLayout, QLabel, QPushButton, QTextBrowser, QGroupBox, QTabWidget, QWidget

from gui.feedback_states import make_action_links


BTN_STYLE = """
QPushButton {
    background-color: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    min-width: 120px;
}
QPushButton:hover {
    background-color: #e3f2fd;
    border-color: #2196f3;
}
QPushButton:pressed {
    background-color: #bbdefb;
}
QPushButton#primary {
    background-color: #2196f3;
    color: white;
    border: none;
}
QPushButton#primary:hover {
    background-color: #1976d2;
}
"""

GROUP_STYLE = """
QGroupBox {
    font-weight: bold;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    background-color: #fafafa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
"""

TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    top: -1px;
}
QTabBar::tab {
    background: #f5f5f5;
    border: 1px solid #e0e0e0;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background: white;
    border-bottom-color: white;
}
"""


def show_system_dialog(self):
    """系统窗口 - 标签页卡片式"""
    d, l = self._dlg("系统", w=680, h=680)
    d.setStyleSheet(BTN_STYLE + GROUP_STYLE + TAB_STYLE)

    result = QTextBrowser()
    result.setFixedHeight(120)
    result.setReadOnly(True)

    tabs = QTabWidget()

    # ===== 标签1: 状态与自检 =====
    tab1 = QWidget()
    l1 = QVBoxLayout(tab1)

    box1 = QGroupBox("📊 状态总览")
    l1a = QVBoxLayout(box1)
    status_bar = QTextBrowser()
    status_bar.setFixedHeight(110)
    status_bar.setReadOnly(True)
    l1a.addWidget(status_bar)

    def _disk_check():
        try:
            import shutil as _shutil
            free_gb = _shutil.disk_usage(self.trunk.base or ".").free / (1024 ** 3)
        except Exception as e:
            return {"ok": False, "hint": "读不到磁盘: %s" % str(e)[:40]}
        return {"ok": free_gb > 1.0, "warn": free_gb < 3.0,
                "hint": "剩余 %.1f GB" % free_gb}

    def _trace_check():
        # 只在 trace 已加载时统计：这里在 GUI 线程跑，不能触发懒加载
        tr = (self.trunk.modules or {}).get("trace")
        if tr is None:
            return {"ok": True, "hint": "未启用（打开 Trace 回看后统计）"}
        try:
            s = tr.summary(limit=200, n=3)
        except Exception as e:
            return {"ok": False, "hint": "读不到 Trace: %s" % str(e)[:40]}
        return {"ok": s.get("failures", 0) == 0,
                "warn": 0 < s.get("failures", 0) <= 3,
                "hint": "%d 事件 / 失败 %d" % (s.get("count", 0),
                                              s.get("failures", 0))}

    def _refresh_status():
        try:
            n = len(self.trunk.modules) + len(self.trunk._lazy)
            errs = 0
            try:
                r = self.trunk.call("error_lib", "list")
                errs = (r or {}).get("未修复", 0) if isinstance(r, dict) else 0
            except Exception as e:
                _x6_swallowed(__name__, e)
                pass
            # 读当前模型状态
            try:
                cfg = self.trunk.config or {}
                model_mode = cfg.get("model_mode", "本地模型")
                if "云" in model_mode:
                    model_name = cfg.get("cloud_model", "glm-4-flash")
                    dot_color = "🟢"
                else:
                    model_name = cfg.get("local_model", "本地Ollama")
                    dot_color = "🔵"
                model_status = "%s 当前: %s → %s" % (dot_color, model_mode, model_name)
            except Exception:
                model_status = "🟢 当前模型: 未知"
            # 体检报告（D4）：把模块/错误库/模型/磁盘/Trace 聚合成一句话
            health_line = ""
            try:
                from core.health_report import build_report
                rep = build_report([
                    ("模块", lambda: {"ok": n > 0, "hint": "共 %d 个" % n}),
                    ("错误库", lambda: {"ok": errs == 0, "warn": errs <= 3,
                                       "hint": "%d 条未修复" % errs}),
                    ("模型", lambda: {"ok": True, "warn": "未知" in model_status,
                                      "hint": model_status}),
                    ("磁盘", _disk_check),
                    ("Trace", _trace_check),
                ])
                icon = {"pass": "✅", "warn": "⚠", "fail": "❌"}.get(
                    rep["overall"], "❔")
                health_line = "\n🩺 体检: %s 通过 %d / 警告 %d / 失败 %d" % (
                    icon, rep["pass"], rep["warn"], rep["fail"])
                bad = [i["name"] + ("（" + i["hint"] + "）" if i.get("hint") else "")
                       for i in rep["items"] if i["status"] != "pass"]
                if bad:
                    health_line += " | 需关注: " + "；".join(bad[:3])
            except Exception as e:
                _x6_swallowed(__name__, e, "health report")
            status_bar.setPlainText("📊 模块: %d | 未修复错误: %d | 状态: %s\n%s%s"
                % (n, errs, "✅ 正常" if errs == 0 else "⚠ 有错误", model_status,
                   health_line))
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass
    _refresh_status()
    l1.addWidget(box1)

    box2 = QGroupBox("🩺 自检与修复")
    l2 = QVBoxLayout(box2)
    btn1 = QPushButton("🔪 深度自检报告")
    btn1.clicked.connect(lambda: self._bg_call(result, self.trunk._deep_check, "深度自检"))
    l2.addWidget(btn1)

    def _clear_errors():
        self._bg_call(result, lambda: self.trunk.call("error_lib", "clear_all"),
                      "清空错误库")

    # 这个入口的历史：
    #   一版调 trunk.call("error_lib", "auto_fix") —— error_lib 没有这个方法，
    #   点了只弹「功能不可用」；
    #   一版改调 self_heal.run() —— 但那个模块名字叫"自愈"、实际只把记录标成
    #   已处理、一行代码都不改，还会顺带弹一次确认窗。现已删除。
    # 现在如实做成它一直实际上在做的事：把错误记录标记为已处理并清理掉。
    # 小白使用说明 —— 之前项目里只有 700 行的架构文档，没有一份
    # "点哪个按钮会发生什么"的说明，用户遇到问题只能来问。

    def _open_doc():
        import os as _os
        p = _os.path.join(getattr(self.trunk, "base", ".") or ".",
                          "使用说明-小白版.txt")
        if not _os.path.exists(p):
            result.setText("找不到说明文件：%s" % p)
            return
        try:
            # Windows 下用系统默认程序打开（记事本能正确显示 UTF-8）
            _os.startfile(p)
            result.setText("已打开 %s" % _os.path.basename(p))
        # 静默是故意的？—— 不是。打不开要如实说，并给出路径让用户自己开
        except Exception as e:
            result.setText("打不开（%s）。文件在这里，手动打开即可：\n%s"
                           % (str(e)[:60], p))

    l2.addWidget(make_action_links([
        ("🩺 重新体检", _refresh_status),
        ("🗑 清空错误库（只清记录，不改代码）", _clear_errors),
        ("📖 使用说明（小白版）", _open_doc),
    ]))
    l1.addWidget(box2)

    l1.addWidget(QLabel("运行结果:"))
    l1.addWidget(result)
    tabs.addTab(tab1, "📊 状态与自检")

    # ===== 标签2: 备份与更新 =====
    tab2 = QWidget()
    l3 = QVBoxLayout(tab2)
    box3 = QGroupBox("💾 备份与更新")
    l3a = QVBoxLayout(box3)
    l3a.addWidget(make_action_links([
        ("💾 立即备份", lambda: self._bg_call(
            result, lambda: self.trunk.call("backup", "run"), "备份")),
        ("📤 导出备份（加密）", lambda: self._export_backup_ui(result)),
    ]))
    # 「🔁 自动更新闭环」按钮已撤：这条能力现在声明成了 auto_update，
    # 在命令面板（Ctrl+K）里搜"自动更新"就能跑，也能直接对聊天说。
    # 撤按钮不是删功能 —— 是让同一个能力有统一入口，不用人记着去哪个面板点。
    l3.addWidget(box3)
    tabs.addTab(tab2, "💾 备份与更新")

    # ===== 标签3: 学习与任务 =====
    #
    # 这一组按钮原来有 4 个（采纳建议 / 开始学习 / 编程项目实战 / 任务闭环），
    # 其中 3 个已撤，理由分别是：
    #   「✅ 采纳建议（学第一条）」—— **一直是坏的**：它读的是 sug 文本框的第一行，
    #       而那个框全项目只有一处 setPlainText("🤔 正在生成建议...")，
    #       之后再没人填过内容 —— 所以它每次都拿这句占位符去网上搜。
    #   「🚀 开始学习」—— 能力已声明成 learn_topic（learning_loop.run），
    #       命令面板里搜"学习"就能跑，也能直接说「学一下 xxx」。
    #   「🎯 任务闭环」—— 能力已声明成 task_goal（task_loop.run），同上。
    # 撤按钮 = 把同一能力收进统一入口，不是删功能。
    tab3 = QWidget()
    l4 = QVBoxLayout(tab3)

    box4 = QGroupBox("🎯 学习与任务")
    l4a = QVBoxLayout(box4)
    l4a.addWidget(QLabel(
        "学习、任务闭环、自动更新这些都改成统一入口了：\n"
        "· 按 Ctrl+K 打开命令面板搜「学习」「任务闭环」「自动更新」\n"
        "· 或者直接对聊天说：「学一下 异步编程」「帮我写一个计算器脚本」"))
    l4.addWidget(box4)

    box6 = QGroupBox("🎯 任务闭环")
    l6a = QVBoxLayout(box6)
    l6a.addWidget(make_action_links([
        ("🚀 编程项目实战", lambda: self._run_learn_one(result)),
    ]))
    # 「🎯 任务闭环（拆解执行目标）」按钮已撤：能力声明成了 task_goal
    # （task_loop.run），命令面板搜"任务闭环"或直接说目标都能跑。
    l4.addWidget(box6)

    tabs.addTab(tab3, "🎯 学习与任务")

    # ===== 标签4: 模块功能 =====
    tab4 = QWidget()
    l7 = QVBoxLayout(tab4)
    box7 = QGroupBox("📦 已安装模块功能")
    l7a = QVBoxLayout(box7)
    mods = [(n, m.get("button")) for n, m in (self.trunk.module_meta or {}).items()
            if m.get("button") and n != "voice"
            and not (isinstance(m.get("button"), dict) and m.get("button").get("action") == "run")]
    if mods:
        # 模块自带的功能入口也是"一次性动作"，统一做成链接，别再堆按钮
        l7a.addWidget(make_action_links([
            (b.get("label", name),
             lambda n=name, a=b.get("action", "run"):
             self._module_button_clicked(n, a))
            for name, b in mods
        ]))
    else:
        l7a.addWidget(QLabel("（还没有模块按钮）"))
    l7.addWidget(box7)
    tabs.addTab(tab4, "📦 模块功能")

    l.addWidget(tabs)
    d.show()
    return d


