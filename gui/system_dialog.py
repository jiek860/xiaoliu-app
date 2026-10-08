# -*- coding: utf-8 -*-
"""系统窗口 v2.0 - 标签页卡片式（仿设置窗口）"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QMessageBox,
                             QTextBrowser, QTextEdit, QGroupBox, QTabWidget, QWidget)


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
    btn2 = QPushButton("自修复")
    btn2.clicked.connect(lambda: self._bg_call(result, lambda: self.trunk.call("error_lib", "auto_fix"), "自修复"))
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

    box4 = QGroupBox("🎯 学习建议")
    l4a = QVBoxLayout(box4)
    l4a.addWidget(QLabel("💡 根据聊天生成的学习建议:"))
    sug = QTextEdit()
    sug.setFixedHeight(80)
    sug.setPlainText("🤔 正在生成建议...")
    l4a.addWidget(sug)
    btn6 = QPushButton("✅ 采纳建议（学第一条）")
    btn6.clicked.connect(lambda: (result.setPlainText("开始学习: "+sug.toPlainText().split("\n")[0][:50]),
                         self.trunk.call("proactive_learner", "learn", sug.toPlainText().split("\n")[0])))
    l4a.addWidget(btn6)
    l4.addWidget(box4)

    box5 = QGroupBox("🌐 网址 / 主题学习")
    l5a = QVBoxLayout(box5)
    url = QLineEdit()
    url.setPlaceholderText("输入网址或学习主题，点开始学习")
    l5a.addWidget(url)
    def _sys_start_learn():
        u = url.text().strip()
        if not u:
            result.setPlainText("请先输入网址或主题再点开始学习")
            return
        result.setPlainText(str(self.trunk.call("proactive_learner", "learn", u)))
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


