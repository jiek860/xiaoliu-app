# -*- coding: utf-8 -*-
"""系统窗口 v2.0 - 标签页卡片式（仿设置窗口）"""
from PyQt5.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QTextEdit, QGroupBox, QTabWidget, QWidget


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
    status_bar.setFixedHeight(60)
    status_bar.setReadOnly(True)
    l1a.addWidget(status_bar)
    def _refresh_status():
        try:
            n = len(self.trunk.modules) + len(self.trunk._lazy)
            errs = 0
            try:
                r = self.trunk.call("error_lib", "list")
                errs = (r or {}).get("未修复", 0) if isinstance(r, dict) else 0
            except Exception:
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
            status_bar.setPlainText("📊 模块: %d | 未修复错误: %d | 状态: %s\n%s"
                % (n, errs, "✅ 正常" if errs == 0 else "⚠ 有错误", model_status))
        except Exception:
            pass
    _refresh_status()
    l1.addWidget(box1)

    box2 = QGroupBox("🩺 自检与修复")
    l2 = QVBoxLayout(box2)
    btn1 = QPushButton("🔪 深度自检报告")
    btn1.clicked.connect(lambda: self._bg_call(result, self.trunk._deep_check, "深度自检"))
    l2.addWidget(btn1)
    btn2 = QPushButton("🗑 清空错误库")
    # 这个按钮的历史：
    #   一版调 trunk.call("error_lib", "auto_fix") —— error_lib 没有这个方法，
    #   点了只弹「功能不可用」；
    #   一版改调 self_heal.run() —— 但那个模块名字叫"自愈"、实际只把记录标成
    #   已处理、一行代码都不改，还会顺带弹一次确认窗。现已删除。
    # 现在如实做成它一直实际上在做的事：把错误记录标记为已处理并清理掉。
    btn2.setToolTip("把所有未修复的错误标记为已处理并清理（不改代码）")
    btn2.clicked.connect(lambda: self._bg_call(
        result, lambda: self.trunk.call("error_lib", "clear_all"), "清空错误库"))
    l2.addWidget(btn2)
    l1.addWidget(box2)

    l1.addWidget(QLabel("运行结果:"))
    l1.addWidget(result)
    tabs.addTab(tab1, "📊 状态与自检")

    # ===== 标签2: 备份与更新 =====
    tab2 = QWidget()
    l3 = QVBoxLayout(tab2)
    box3 = QGroupBox("💾 备份与更新")
    l3a = QVBoxLayout(box3)
    btn3 = QPushButton("备份")
    btn3.clicked.connect(lambda: self._bg_call(result, lambda: self.trunk.call("backup", "run"), "备份"))
    l3a.addWidget(btn3)
    btn4 = QPushButton("📤 导出备份(加密)")
    btn4.clicked.connect(lambda: self._export_backup_ui(result))
    l3a.addWidget(btn4)
    btn5 = QPushButton("🔁 自动更新闭环")
    btn5.clicked.connect(lambda: self._run_auto_update_ui(result))
    l3a.addWidget(btn5)
    l3.addWidget(box3)
    tabs.addTab(tab2, "💾 备份与更新")

    # ===== 标签3: 学习与任务 =====
    tab3 = QWidget()
    l4 = QVBoxLayout(tab3)

    def _learn_topic(topic):
        """让学习闭环去学一个网址/主题：先搜资料，再提炼入库。

        原来是 trunk.call("proactive_learner", "learn", ...) ——
        proactive_learner 这个模块早已改名成 active_learning，而 active_learning
        也没有 learn 方法，所以「开始学习」「采纳建议」两个按钮一直是坏的。
        现在直接走 learning_loop 的 fetch + store（本来就是这套流程的两步）。
        """
        topic = (topic or "").strip()
        if not topic:
            return "请先输入网址或主题"
        ll = self.trunk.modules.get("learning_loop") or self.trunk._load_lazy("learning_loop")
        if not ll:
            return "学习闭环模块没加载起来"
        try:
            items = ll.fetch(topic)
        except Exception as e:
            return "搜索失败: %s" % str(e)[:80]
        if not items:
            return "没搜到关于「%s」的资料（检查联网开关 / deep_search）" % topic[:40]
        try:
            ll.store("手动指定", topic, items)
        except Exception as e:
            return "已搜到 %d 条，但入库失败: %s" % (len(items), str(e)[:60])
        return "已学习「%s」：搜到 %d 条，已提炼入库" % (topic[:40], len(items))

    box4 = QGroupBox("🎯 学习建议")
    l4a = QVBoxLayout(box4)
    l4a.addWidget(QLabel("💡 根据聊天生成的学习建议:"))
    sug = QTextEdit()
    sug.setFixedHeight(80)
    sug.setPlainText("🤔 正在生成建议...")
    l4a.addWidget(sug)
    btn6 = QPushButton("✅ 采纳建议（学第一条）")
    def _adopt_suggestion():
        first = sug.toPlainText().split("\n")[0].strip()
        result.setPlainText("开始学习: " + first[:50])
        result.setPlainText(_learn_topic(first))
    btn6.clicked.connect(_adopt_suggestion)
    l4a.addWidget(btn6)
    l4.addWidget(box4)

    box5 = QGroupBox("🌐 网址 / 主题学习")
    l5a = QVBoxLayout(box5)
    url = QLineEdit()
    url.setPlaceholderText("输入网址或学习主题，点开始学习")
    l5a.addWidget(url)
    def _sys_start_learn():
        result.setPlainText(_learn_topic(url.text()))
    btn7 = QPushButton("🚀 开始学习")
    btn7.setObjectName("primary")
    btn7.clicked.connect(_sys_start_learn)
    l5a.addWidget(btn7)
    l4.addWidget(box5)

    box6 = QGroupBox("🎯 任务闭环")
    l6a = QVBoxLayout(box6)
    btn8 = QPushButton("🚀 编程项目实战")
    btn8.clicked.connect(lambda: self._run_learn_one(result))
    l6a.addWidget(btn8)
    btn9 = QPushButton("🎯 任务闭环（拆解执行目标）")
    btn9.clicked.connect(lambda: self._run_task_goal(result))
    l6a.addWidget(btn9)
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
        for name, b in mods:
            label = b.get("label", name)
            action = b.get("action", "run")
            btn = QPushButton(label)
            btn.setToolTip("%s | %s" % (b.get("desc", ""), name))
            btn.clicked.connect(lambda checked, n=name, a=action: self._module_button_clicked(n, a))
            l7a.addWidget(btn)
    else:
        l7a.addWidget(QLabel("（还没有模块按钮）"))
    l7.addWidget(box7)
    tabs.addTab(tab4, "📦 模块功能")

    l.addWidget(tabs)
    d.show()


