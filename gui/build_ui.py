# -*- coding: utf-8 -*-
"""主界面布局构建。

结构拆成五块，方便统一做模式显隐：
    topbar / sidebar / chat / composer / statusbar

简单模式：只保留新建、对话、任务、资料、设置 + 附件、语音、发送。
高级模式：上述入口之外，恢复模块按钮、模型选择、代码编辑器、实时对话、
          登录、清空以及安全中心 / 插件 / MCP / 记忆 / 日志等入口。

所有显隐统一由本文件的 _apply_mode() 控制；功能定义在
core/feature_registry.py，主窗口不要自己写第二套可见性规则。
"""
import os

from PyQt5.QtCore import Qt, QRect, QPoint
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QFrame, QTextEdit, QDialog, QMessageBox, QRubberBand, QListWidgetItem,
    QMenu, QComboBox, QScrollArea,
)

from core.feature_registry import SIMPLE, ADVANCED, is_visible, primary_features
from gui.ui_mode import normalize_mode


def _visible(widget, show):
    if widget is not None:
        try:
            widget.setVisible(bool(show))
        except Exception:  # 静默是故意的
            pass


def _small_button(text, tip=""):
    b = QPushButton(text)
    if tip:
        b.setToolTip(tip)
    b.setStyleSheet(
        "QPushButton{background:#f5f6f8;color:#333;border:1px solid #e5e6eb;"
        "padding:6px 10px;border-radius:8px;font-size:12px;text-align:center;}"
        "QPushButton:hover{background:#eef5ff;border-color:#4a9eff;color:#1976d2;}")
    return b


def _nav_item(text, key):
    it = QListWidgetItem(text)
    it.setData(Qt.UserRole, key)
    return it


def _build_topbar(win):
    top = QWidget()
    top.setObjectName("topbar")
    tl = QHBoxLayout(top)
    tl.setContentsMargins(14, 8, 14, 8)
    tl.setSpacing(8)

    win.brand_label = QLabel("✨ 小6智能体")
    win.brand_label.setStyleSheet("font-size:16px;font-weight:700;color:#1f2937;")
    tl.addWidget(win.brand_label)
    tl.addStretch(1)

    _model_mode = "本地路由"
    try:
        _model_mode = win.trunk.config.get("model_mode", "本地路由")
    except Exception:  # 静默是故意的
        pass
    win.model_status_label = QLabel("模型：%s" % _model_mode)
    win.model_status_label.setToolTip("当前模型状态；高级模式可点模型按钮切换")
    win.model_status_label.setStyleSheet(
        "color:#667085;background:#f5f6f8;border-radius:10px;padding:4px 10px;"
        "font-size:12px;")
    tl.addWidget(win.model_status_label)

    win.more_btn = _small_button("⋯ 更多", "低频入口都在这里")
    win.more_btn.setObjectName("moreBtn")
    win.more_btn.clicked.connect(win._show_more_menu)
    tl.addWidget(win.more_btn)

    win.avatar_btn = QPushButton("👤")
    win.avatar_btn.setObjectName("avatarBtn")
    win.avatar_btn.setFixedSize(34, 30)
    win.avatar_btn.setToolTip("账号、模式切换和高级功能")
    win.avatar_btn.setStyleSheet(
        "QPushButton{background:#eef5ff;color:#1976d2;border:1px solid #d6e8ff;"
        "border-radius:15px;padding:0;text-align:center;font-size:15px;}"
        "QPushButton:hover{background:#dcecff;}")
    win.avatar_btn.clicked.connect(win._show_avatar_menu)
    tl.addWidget(win.avatar_btn)

    win.topbar = top
    return top


def _build_sidebar(win):
    sidebar_w = QWidget()
    sidebar_w.setObjectName("sidebar")
    sidebar_w.setFixedWidth(230)
    sidebar_w.setStyleSheet(
        "QWidget#sidebar{background:white;border-right:1px solid #e0e0e0;}")

    # 左栏内容可能比窗口高（尤其高级模式 + 多个模块按钮）。
    # 放进滚区域，保证最下面的模块按钮也能滚动到，而不是被裁掉。
    sidebar_scroll = QScrollArea()
    sidebar_scroll.setObjectName("sidebarScroll")
    sidebar_scroll.setWidgetResizable(True)
    sidebar_scroll.setFrameShape(QFrame.NoFrame)
    sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sidebar_scroll.setStyleSheet(
        "QScrollArea#sidebarScroll{background:white;border:none;}"
        "QScrollBar:vertical{background:#f5f6f8;width:8px;margin:0;}"
        "QScrollBar::handle:vertical{background:#c9ced8;border-radius:4px;"
        "min-height:24px;}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
    sidebar_content = QWidget()
    sidebar_content.setObjectName("sidebarContent")
    sidebar_content.setMinimumWidth(200)
    sidebar = QVBoxLayout(sidebar_content)
    sidebar.setContentsMargins(10, 10, 10, 10)
    sidebar.setSpacing(8)
    sidebar_scroll.setWidget(sidebar_content)
    outer_sidebar = QVBoxLayout(sidebar_w)
    outer_sidebar.setContentsMargins(0, 0, 0, 0)
    outer_sidebar.addWidget(sidebar_scroll)
    win.sidebar_scroll = sidebar_scroll
    win.sidebar_content = sidebar_content

    win.new_chat_btn = QPushButton("＋ 新建对话")
    win.new_chat_btn.setObjectName("newChatBtn")
    win.new_chat_btn.setToolTip("创建一个新的聊天对话")
    win.new_chat_btn.setStyleSheet(
        "QPushButton{background:#4a9eff;color:white;border:none;padding:10px;"
        "border-radius:12px;font-size:13px;text-align:left;}"
        "QPushButton:hover{background:#3a8eef;}")
    win.new_chat_btn.clicked.connect(win._new_session)
    sidebar.addWidget(win.new_chat_btn)

    win.nav_list = QListWidget()
    win.nav_list.setObjectName("navList")
    win.nav_list.setFixedHeight(160)
    win.nav_list.setStyleSheet(
        "QListWidget{background:transparent;border:none;font-size:13px;}"
        "QListWidget::item{padding:9px 10px;border-radius:8px;}"
        "QListWidget::item:hover{background:#f0f5ff;}"
        "QListWidget::item:selected{background:#e3f2fd;color:#1976d2;}")
    for text, key in (("💬  对话", "chat"), ("🧭  任务", "task"),
                      ("📚  资料", "resources"), ("⚙  设置", "settings")):
        win.nav_list.addItem(_nav_item(text, key))
    win.nav_list.itemClicked.connect(win._on_nav_clicked)
    sidebar.addWidget(win.nav_list)

    win.history_label = QLabel(
        "<span style='color:#888;font-size:11px;'>最近对话</span>")
    sidebar.addWidget(win.history_label)
    win.session_list = QListWidget()
    win.session_list.setStyleSheet(
        "QListWidget{background:transparent;color:#333;border:none;font-size:13px;}"
        "QListWidget::item{padding:8px;border-radius:6px;}"
        "QListWidget::item:hover{background:#f0f0f0;}"
        "QListWidget::item:selected{background:#e3f2fd;color:#1976d2;}")
    _it = QListWidgetItem("💬 默认对话")
    _it.setData(Qt.UserRole, "default")
    win.session_list.addItem(_it)
    win.session_list.itemClicked.connect(win._on_session_clicked)
    sidebar.addWidget(win.session_list, 1)

    # 高级模式才显示的常驻功能入口
    win.sidebar_advanced_box = QWidget()
    av = QVBoxLayout(win.sidebar_advanced_box)
    av.setContentsMargins(0, 4, 0, 0)
    av.setSpacing(2)
    av.addWidget(QLabel(
        "<span style='color:#888;font-size:11px;'>高级功能</span>"))

    def _adv_btn(attr, text, tip, fn):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setStyleSheet(
            "QPushButton{background:transparent;color:#333;border:none;"
            "padding:7px 8px;border-radius:8px;font-size:12px;text-align:left;}"
            "QPushButton:hover{background:#f0f5ff;color:#1976d2;}")
        b.clicked.connect(fn)
        setattr(win, attr, b)
        av.addWidget(b)
        return b

    _adv_btn("task_center_btn", "🧭  任务中心", "统一任务页面",
             win.open_task_center)
    _adv_btn("security_center_btn", "🛡  安全中心", "权限 / 网络 / 审计",
             win.security_center_dialog)
    _adv_btn("plugin_market_btn", "🔌  插件市场", "安装和管理模块",
             win.plugin_dialog)
    _adv_btn("mcp_btn", "🧷  MCP", "MCP 服务器管理", win.mcp_dialog)
    _adv_btn("memory_btn", "🧠  记忆", "记忆时间线 / 图谱", win.memory_view_dialog)
    _adv_btn("logs_btn", "📋  日志", "运行日志与错误", win.log_dialog)
    _adv_btn("command_palette_btn", "⌘  命令面板", "Ctrl+K",
             win.command_palette)

    # 已安装模块自己声明的按钮
    try:
        from core.module_buttons import load_buttons
        mod_btns = load_buttons(getattr(win, "base", None))
    except Exception:  # 静默是故意的
        mod_btns = []
    win.sidebar_modules_box = QWidget()
    mb = QVBoxLayout(win.sidebar_modules_box)
    mb.setContentsMargins(0, 4, 0, 0)
    mb.setSpacing(2)
    win.sidebar_module_count_label = QLabel(
        "<span style='color:#888;font-size:11px;'>模块（%d）</span>"
        % len(mod_btns))
    win.sidebar_module_count_label.setToolTip(
        "共 %d 个已安装模块按钮" % len(mod_btns))
    mb.addWidget(win.sidebar_module_count_label)
    if mod_btns:
        for item in mod_btns:
            label = str(item.get("label") or "").strip()
            if not label:
                continue
            b = QPushButton(label)
            b.setMinimumHeight(28)
            b.setToolTip("打开模块：%s\n动作：%s"
                         % (item["title"], item["action"]))
            b.setStyleSheet(
                "QPushButton{background:transparent;color:#333;border:none;"
                "padding:7px 8px;border-radius:8px;font-size:12px;"
                "text-align:left;}"
                "QPushButton:hover{background:#f0f5ff;}")
            b.clicked.connect(
                lambda _checked=False, n=item["name"], a=item["action"]:
                win._module_button_clicked(n, a))
            mb.addWidget(b)
    else:
        empty = QLabel("暂无模块按钮")
        empty.setStyleSheet("color:#aaa;font-size:11px;padding:4px 8px;")
        mb.addWidget(empty)
    av.addWidget(win.sidebar_modules_box)
    sidebar.addWidget(win.sidebar_advanced_box)

    # 登录 / 清空聊天（高级模式）
    win.sidebar_bottom_advanced = QWidget()
    br = QHBoxLayout(win.sidebar_bottom_advanced)
    br.setContentsMargins(0, 0, 0, 0)
    br.setSpacing(6)
    win.login_btn_sb = _small_button("🔑 登录", "登录 / 切换账号")
    win.login_btn_sb.clicked.connect(win.show_login)
    br.addWidget(win.login_btn_sb)
    win.clear_btn_sb = _small_button("🗑 清空", "清空聊天")
    win.clear_btn_sb.clicked.connect(win._clear_chat)
    br.addWidget(win.clear_btn_sb)
    sidebar.addWidget(win.sidebar_bottom_advanced)

    # 按内容最小高度撑开：按钮多时出现滚动条，而不是把下半截压没。
    try:
        sidebar_content.setMinimumHeight(sidebar_content.minimumSizeHint().height())
    except Exception:  # 静默是故意的
        pass
    win.sidebar = sidebar_w
    return sidebar_w


def _build_chat(win):
    right = QVBoxLayout()
    right.setContentsMargins(0, 0, 0, 0)
    right.setSpacing(0)

    # 首页空状态：三张卡片
    win.empty_state = QFrame()
    win.empty_state.setStyleSheet(
        "QFrame{background:#fbfcff;border:1px solid #e7ecf5;"
        "border-radius:12px;margin:10px;}")
    el = QVBoxLayout(win.empty_state)
    el.setContentsMargins(18, 14, 18, 14)
    title = QLabel("今天想做什么？")
    title.setStyleSheet("font-size:17px;font-weight:700;color:#1f2937;")
    el.addWidget(title)
    sub = QLabel("配好模型，说一句话，或者把复杂目标交给任务模式。")
    sub.setStyleSheet("color:#667085;font-size:12px;")
    el.addWidget(sub)
    cards_row = QHBoxLayout()
    win.guide_cards = []
    for i in range(3):
        b = QPushButton("")
        b.setMinimumHeight(64)
        b.setStyleSheet(
            "QPushButton{background:white;border:1px solid #e1e8f2;"
            "border-radius:10px;padding:10px;text-align:left;font-size:13px;}"
            "QPushButton:hover{border-color:#4a9eff;background:#f5f9ff;}")
        b.clicked.connect(lambda _checked=False, idx=i: win._run_guide_card(idx))
        cards_row.addWidget(b, 1)
        win.guide_cards.append(b)
    el.addLayout(cards_row)
    right.addWidget(win.empty_state)

    from gui.chat_view import ChatView
    win.chat = ChatView(win, base_dir=win.base)
    win.chat.setContextMenuPolicy(Qt.CustomContextMenu)
    win.chat.actionRequested.connect(win._on_chat_action)

    def _chat_menu(pos):
        menu = win.chat.createStandardContextMenu()
        menu.setStyleSheet(
            "QMenu{background:white;color:black;border:1px solid #ddd;}"
            "QMenu::item:selected{background:#e3f2fd;}")
        for a in menu.actions():
            txt = a.text()
            if "Copy" in txt:
                a.setText("复制")
            elif "Paste" in txt:
                a.setText("粘贴")
            elif "Cut" in txt:
                a.setText("剪切")
            elif "Undo" in txt:
                a.setText("撤销")
            elif "Redo" in txt:
                a.setText("重做")
            elif "Select All" in txt:
                a.setText("全选")
        menu.addSeparator()
        edit_action = menu.addAction(" 编辑上一条消息")
        edit_action.triggered.connect(win.edit_last_user_message)
        regen_action = menu.addAction(" 重新生成上一条回复")
        regen_action.triggered.connect(win.regenerate_last_reply)
        branch_action = menu.addAction(" 从当前对话创建分支")
        branch_action.triggered.connect(win.branch_current_conversation)
        menu.addSeparator()
        sel = win.chat.textCursor().selectedText().strip()
        task_action = menu.addAction(" 转为任务")
        task_action.triggered.connect(
            lambda: win._convert_to_task(sel or win.input.toPlainText().strip()))
        clear_action = menu.addAction(" 清空聊天")
        clear_action.triggered.connect(win._clear_chat)
        if sel:
            cite = menu.addAction(" 引用选中文本")
            cite.triggered.connect(
                lambda: win.input.insert("【引用】" + sel[:200] + "\n"))
        menu.exec_(win.chat.mapToGlobal(pos))

    win.chat.customContextMenuRequested.connect(_chat_menu)
    win.chat.setReadOnly(True)
    win.chat.setOpenLinks(False)
    right.addWidget(win.chat, 1)

    try:
        fs = int(win.trunk.config.get("font_size", "16px").replace("px", ""))
        win.chat.setStyleSheet(
            "font-size:%dpx;background-color:#f5f5f5;border:none;"
            "border-radius:8px;padding:10px;" % fs)
    except Exception:  # 静默是故意的
        pass
    return right


def _build_composer(win):
    input_frame = QFrame()
    input_frame.setObjectName("composer")
    input_frame.setStyleSheet(
        "QFrame#composer{border:1px solid #ddd;border-radius:12px;"
        "background:white;}")
    fl = QVBoxLayout(input_frame)
    fl.setContentsMargins(12, 10, 12, 8)
    fl.setSpacing(6)

    win.input = QTextEdit()
    win.input.setAcceptDrops(True)
    win.input.installEventFilter(win)
    win.input.setPlaceholderText("说一句话，或者直接描述一个任务（Enter 发送）")
    win.input.setMinimumHeight(60)
    win.input.setMaximumHeight(120)
    win.input.setStyleSheet(
        "border:none;background:transparent;font-size:14px;")
    win.input.setContextMenuPolicy(Qt.CustomContextMenu)

    def _input_menu(pos):
        menu = win.input.createStandardContextMenu()
        menu.setStyleSheet(
            "QMenu{background:white;color:black;border:1px solid #ddd;}"
            "QMenu::item:selected{background:#e3f2fd;}")
        for a in menu.actions():
            txt = a.text()
            if "Copy" in txt:
                a.setText("复制")
            elif "Paste" in txt:
                a.setText("粘贴")
            elif "Cut" in txt:
                a.setText("剪切")
            elif "Undo" in txt:
                a.setText("撤销")
            elif "Redo" in txt:
                a.setText("重做")
            elif "Select All" in txt:
                a.setText("全选")
        menu.exec_(win.input.mapToGlobal(pos))
    win.input.customContextMenuRequested.connect(_input_menu)
    fl.addWidget(win.input)

    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(6)

    win.plus_btn = QPushButton("+")
    win.plus_btn.setFixedSize(36, 30)
    win.plus_btn.setToolTip("附件 / 截图 / 上传文件")
    win.plus_btn.setStyleSheet(
        "QPushButton{background:#4a9eff;color:white;border:none;"
        "border-radius:8px;font-size:18px;font-weight:bold;padding:0;"
        "text-align:center;qproperty-alignment:AlignCenter;}"
        "QPushButton:hover{background:#3a8eef;}")
    win.plus_btn.clicked.connect(win._show_plus_menu)
    btn_row.addWidget(win.plus_btn)

    win.mode_combo = QComboBox()
    win.mode_combo.addItems(["聊天", "任务"])
    win.mode_combo.setFixedWidth(78)
    win.mode_combo.setToolTip("聊天：普通问答；任务：拆解、执行并显示结果")
    win.mode_combo.currentIndexChanged.connect(win._on_composer_mode_changed)
    btn_row.addWidget(win.mode_combo)

    win.voice_btn = _small_button("🎙 语音", "语音输入 / 输入切换")
    win.voice_btn.setFixedHeight(30)
    win.voice_btn.clicked.connect(win._voice_btn_clicked)
    btn_row.addWidget(win.voice_btn)

    win.realtime_btn = _small_button("🎧 实时对话", "实时语音对话")
    win.realtime_btn.setFixedHeight(30)
    win.realtime_btn.clicked.connect(win._rt_toggle)
    btn_row.addWidget(win.realtime_btn)

    win.model_btn = _small_button("🤖 模型：本地路由", "切换本地 / 云端模型")
    win.model_btn.setFixedHeight(30)
    win.model_btn.clicked.connect(win.switch_model)
    btn_row.addWidget(win.model_btn)
    btn_row.addStretch(1)

    # 2026-10-22：三个入口（编辑器 / Agent 旅程 /  AI 代码 Agent）
    # 合并为「🧰 工作台」一个按钮，点击打开同一窗口。
    win.editor_btn = _small_button(
        "🧰 工作台", "编辑器 + AI 面板同屏（Ctrl+J 收起 AI，F11 全屏）")
    win.editor_btn.setFixedHeight(30)
    win.editor_btn.clicked.connect(win.open_workbench)
    btn_row.addWidget(win.editor_btn)

    win.send_btn = QPushButton("发送")
    win.send_btn.setFixedSize(64, 30)
    win.send_btn.setStyleSheet(
        "QPushButton{background:#4a9eff;color:white;border:none;"
        "border-radius:8px;font-size:13px;font-weight:bold;padding:0;"
        "text-align:center;qproperty-alignment:AlignCenter;}"
        "QPushButton:hover{background:#3a8eef;}"
        "QPushButton:pressed{background:#2a7edf;}")
    win.send_btn.clicked.connect(win.send)
    btn_row.addWidget(win.send_btn)

    fl.addLayout(btn_row)
    return input_frame


def _build_statusbar(win):
    sb = win.statusBar()
    win.ui_mode_label = QLabel("简单模式")
    win.ui_mode_label.setStyleSheet("color:#667085;font-size:11px;padding:0 8px;")
    win.guidance_label = QLabel("")
    win.guidance_label.setStyleSheet("color:#1976d2;font-size:11px;padding:0 8px;")
    win.activity_btn = QPushButton("运行中 0")
    win.activity_btn.setToolTip("查看运行中任务和后台活动")
    win.activity_btn.setStyleSheet(
        "QPushButton{background:#f5f6f8;color:#667085;border:none;"
        "border-radius:8px;padding:2px 9px;font-size:11px;text-align:center;}"
        "QPushButton:hover{background:#eef5ff;color:#1976d2;}")
    win.activity_btn.clicked.connect(win.activity_center_dialog)
    win.local_light = QLabel(" 本地")
    win.local_light.setStyleSheet("color:#0f0;font-size:11px;padding:0 8px;")
    win.cloud_light = QLabel(" 云端")
    win.cloud_light.setStyleSheet("color:#999;font-size:11px;padding:0 8px;")
    win._status_local = win.local_light
    win._status_cloud = win.cloud_light
    sb.addPermanentWidget(win.guidance_label)
    sb.addPermanentWidget(win.activity_btn)
    sb.addPermanentWidget(win.ui_mode_label)
    sb.addPermanentWidget(win.local_light)
    sb.addPermanentWidget(win.cloud_light)


def apply_ui_mode(win, mode=None):
    """统一模式显隐入口。

    只改可见性，不销毁控件  切回高级模式时所有能力原样回来，
    也不会因为反复销毁/重建丢状态。
    """
    if mode is None:
        try:
            mode = win.ui_mode.mode
        except Exception:  # 静默是故意的
            mode = getattr(win, "ui_mode_value", SIMPLE)
    mode = normalize_mode(mode)
    simple = mode == SIMPLE
    win.ui_mode_value = mode

    # 首屏主要入口：两种模式都保留
    for attr in ("new_chat_btn", "nav_list", "session_list", "history_label",
                 "plus_btn", "mode_combo", "voice_btn", "send_btn",
                 "input", "chat", "model_status_label"):
        _visible(getattr(win, attr, None), True)

    # 首屏低频入口：只在高级模式出现
    for attr in ("sidebar_advanced_box", "sidebar_bottom_advanced",
                 "realtime_btn", "model_btn", "editor_btn"):
        _visible(getattr(win, attr, None), not simple)
    # 简单模式不显示更多；切到高级模式后，低频入口统一收进更多。
    _visible(getattr(win, "more_btn", None), not simple)

    # 精简侧栏：简单模式只保留 对话/任务/资料/设置 四项
    if getattr(win, "nav_list", None) is not None:
        win.nav_list.setFixedHeight(160)

    if getattr(win, "mode_combo", None) is not None:
        # 切到任务页后回来，模式选择仍然有效
        win.mode_combo.setVisible(True)

    if getattr(win, "ui_mode_label", None) is not None:
        win.ui_mode_label.setText("简单模式" if simple else "高级模式")
    if getattr(win, "brand_label", None) is not None:
        win.brand_label.setToolTip(
            "普通用户界面：只保留聊天、任务、资料" if simple else
            "高级界面：全部能力可用")
    if getattr(win, "avatar_btn", None) is not None:
        win.avatar_btn.setToolTip(
            "账号 / 切换高级模式 / 更多功能" if simple else
            "账号 / 切换简单模式 / 高级功能")
    if getattr(win, "chat", None) is not None:
        try:
            win.chat.setProperty("ui_mode", mode)
        except Exception:  # 静默是故意的
            pass
    return mode


# 兼容需求里写的函数名
_apply_mode = apply_ui_mode


def build_ui(win):
    """构建主界面布局。win 是 JarvisWindow 实例。"""
    central = QWidget()
    win.setCentralWidget(central)
    main = QVBoxLayout(central)
    main.setContentsMargins(0, 0, 0, 0)
    main.setSpacing(0)

    main.addWidget(_build_topbar(win))

    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)
    body.addWidget(_build_sidebar(win))

    right = _build_chat(win)
    right.addWidget(_build_composer(win))
    body.addLayout(right, stretch=1)
    main.addLayout(body, stretch=1)
    _build_statusbar(win)

    # 统一入口：主窗口和设置窗口都调用它
    win._apply_mode = lambda mode=None: apply_ui_mode(win, mode)
    apply_ui_mode(win, getattr(getattr(win, "ui_mode", None), "mode", SIMPLE))
    return win
