# -*- coding: utf-8 -*-
"""电脑控制窗口 v3.0 - 标签页卡片式（仿设置窗口）"""
import os
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QMessageBox, QListWidget, QTextBrowser, QGroupBox, QTabWidget, QWidget

from gui.feedback_states import make_action_links


BTN_STYLE = """
QPushButton {
    background-color: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    min-width: 90px;
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


def show_computer_dialog(parent, dlg, trunk, chat, set_dialog, kb_dialog):
    """电脑控制窗口 - 标签页卡片式

    控件预算：整窗只留「打开」这一个主按钮，其余（快捷应用、窗口操作、
    系统操作、刷新日志）全部改成动作链接 —— 点一下照样执行，数量不再占控件位。
    """
    d, l = dlg("电脑控制", w=680, h=680)
    d.setStyleSheet(BTN_STYLE + GROUP_STYLE + TAB_STYLE)
    cc = trunk._load_lazy("computer_controller")

    def _run(label, method, *args):
        """统一跑一个电脑操作，并把结果说人话（原来两处重复实现）"""
        try:
            r = trunk.call("computer_controller", method, *args)
        except Exception as e:
            QMessageBox.warning(d, label, "执行失败: " + str(e)[:80])
            return
        if isinstance(r, tuple):
            ok, txt = r
        elif isinstance(r, dict):
            ok, txt = True, "\n".join("%s: %s" % (k, v) for k, v in r.items())
        else:
            ok, txt = True, str(r)
        QMessageBox.information(d, label, ("✅ " if ok else "❌ ") + str(txt))


    # 标签页
    tabs = QTabWidget()

    # ===== 标签1: 状态与应用 =====
    tab1 = QWidget()
    l1 = QVBoxLayout(tab1)

    # 状态
    box1 = QGroupBox("📊 状态总览")
    l1a = QVBoxLayout(box1)
    status = QLabel("🖥️ " + (cc.status_line() if cc else "模块未加载"))
    status.setStyleSheet("color:#2e7d32;font-weight:bold;font-size:14px;")
    l1a.addWidget(status)
    sw = QCheckBox("允许在聊天中自动操作电脑")
    sw.setChecked(bool(trunk.config.get("电脑控制", True)))
    def _toggle(checked):
        trunk.config["电脑控制"] = bool(checked)
        trunk.save_config()
    sw.toggled.connect(_toggle)
    l1a.addWidget(sw)
    l1.addWidget(box1)

    # 应用启动
    box2 = QGroupBox("🚀 应用启动")
    l2 = QVBoxLayout(box2)
    app_input = QLineEdit()
    app_input.setPlaceholderText("输入应用名，如：微信 / vscode / 记事本")
    l2.addWidget(app_input)
    def _open_app():
        name = app_input.text().strip()
        if not name:
            QMessageBox.information(d, "提示", "先输入应用名")
            return
        r = trunk.call("computer_controller", "open_app", name)
        txt = r[1] if isinstance(r, tuple) else str(r)
        QMessageBox.information(d, "启动应用", txt)
    app_input.returnPressed.connect(_open_app)
    # 「打开」是唯一高频动作，但回车即可触发 → 用链接表达，整窗不再有常驻按钮
    l2.addWidget(make_action_links([("打开", _open_app)]))

    quick_apps = [
        ("📝 记事本", "记事本"),
        ("🧮 计算器", "计算器"),
        ("🎨 画图", "画图"),
        ("🌐 浏览器", "浏览器"),
        ("📁 资源管理器", "资源管理器"),
        ("⌨️ 命令提示符", "命令提示符"),
    ]

    def _mk_quick(n):
        def _go():
            try:
                r = trunk.call("computer_controller", "open_app", n)
            except Exception as e:
                chat.append("🖥️ 启动失败: " + str(e)[:60])
                return
            txt = r[1] if isinstance(r, tuple) else str(r)
            chat.append("🖥️ " + txt)
        return _go

    l2.addWidget(make_action_links(
        [(text, _mk_quick(name)) for text, name in quick_apps]))
    l1.addWidget(box2)
    tabs.addTab(tab1, "🖥️ 状态与应用")

    # ===== 标签2: 窗口管理 =====
    tab2 = QWidget()
    l3 = QVBoxLayout(tab2)
    box3 = QGroupBox("🪟 窗口管理")
    l3a = QVBoxLayout(box3)
    win_list = QListWidget()
    win_list.setFixedHeight(200)
    l3a.addWidget(win_list)
    def _refresh_wins():
        win_list.clear()
        try:
            wins = trunk.call("computer_controller", "list_windows") or []
            if isinstance(wins, dict):
                win_list.addItem("读不到窗口: " + str(wins.get("error", "")[:40]))
            else:
                for t in wins:
                    win_list.addItem(t)
        except Exception as e:
            win_list.addItem("读取失败: " + str(e)[:50])
    def _win_action(method):
        def _go():
            item = win_list.currentItem()
            if not item:
                QMessageBox.information(d, "提示", "先在列表里选一个窗口")
                return
            r = trunk.call("computer_controller", method, item.text())
            txt = r[1] if isinstance(r, tuple) else str(r)
            chat.append("🖥️ " + txt)
            _refresh_wins()
        return _go
    win_row = QHBoxLayout()
    win_row.addWidget(make_action_links([
        ("🔄 刷新列表", _refresh_wins),
        ("激活窗口", _win_action("activate_window")),
        ("最小化", _win_action("minimize_window")),
        ("关闭窗口", _win_action("close_window")),
    ]))
    win_row.addStretch(1)
    l3a.addLayout(win_row)
    l3.addWidget(box3)
    tabs.addTab(tab2, "🪟 窗口管理")
    _refresh_wins()

    # ===== 标签3: 系统操作 =====
    tab3 = QWidget()
    l4 = QVBoxLayout(tab3)
    box4 = QGroupBox("📸 截屏与系统")
    l4a = QVBoxLayout(box4)
    sys_ops = [
        ("📷 截屏", "screenshot"),
        ("🖱️ 鼠标位置", "mouse_pos"),
        ("💻 系统信息", "system_info"),
        ("📋 剪贴板", "clipboard_get"),
    ]
    l4a.addWidget(make_action_links(
        [(text, lambda m=method, t=text: _run(t, m)) for text, method in sys_ops]))
    l4.addWidget(box4)

    box5 = QGroupBox("⚙️ 高级操作")
    l5a = QVBoxLayout(box5)
    adv_ops = [
        ("📂 白名单目录", "list_dir"),
        ("🔄 取消关机", "cancel_shutdown"),
    ]
    l5a.addWidget(make_action_links(
        [(text, lambda m=method, t=text: _run(t, m)) for text, method in adv_ops]))
    l4.addWidget(box5)
    tabs.addTab(tab3, "⚙️ 系统操作")

    # ===== 标签4: 操作日志 =====
    tab4 = QWidget()
    l6 = QVBoxLayout(tab4)
    box6 = QGroupBox("📜 操作日志")
    l6a = QVBoxLayout(box6)
    log_box = QTextBrowser()
    log_box.setReadOnly(True)
    l6a.addWidget(log_box)
    def _refresh_log():
        try:
            p = os.path.join(trunk.base, "data", "logs", "computer_controller.log")
            if os.path.exists(p):
                lines = [ln for ln in open(p, encoding="utf-8", errors="replace").readlines() if ln.strip()][-50:]
                log_box.setPlainText("".join(lines))
            else:
                log_box.setPlainText("（还没有操作记录）")
        except Exception as e:
            log_box.setPlainText("读取日志失败: " + str(e)[:80])
    refresh_log_btn = make_action_links([("🔄 刷新日志", _refresh_log)])
    l6a.addWidget(refresh_log_btn)
    l6.addWidget(box6)
    tabs.addTab(tab4, "📜 操作日志")

    l.addWidget(tabs)

    d.show()
    return d
