# -*- coding: utf-8 -*-
"""主界面布局构建 - 顶部栏+侧边栏+聊天框+输入框"""
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidget, QTextBrowser, QFrame,
                             QTextEdit, QDialog, QMessageBox, QRubberBand)
from PyQt5.QtCore import Qt, QRect, QPoint


def build_ui(win):
    """构建主界面布局。win 是 JarvisWindow 实例"""
    central = QWidget()
    win.setCentralWidget(central)
    main = QVBoxLayout(central)

    # 顶部
    top = QHBoxLayout()
    top.setContentsMargins(10, 0, 10, 0)
    def do_export():
        from datetime import datetime
        txt = win.chat.toPlainText()
        fn = os.path.join(win.base, r"data\聊天记录_%s.txt") % datetime.now().strftime("%Y%m%d_%H%M%S")
        open(fn, "w", encoding="utf-8").write(txt)
        QMessageBox.information(win, "导出", "已保存到:\n" + fn)

    def do_screenshot():
        screen = win.screen()
        pix = screen.grabWindow(0)
        win._ss_pix = pix
        win._ss_dlg = QDialog(win)
        win._ss_dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        win._ss_dlg.setGeometry(0, 0, screen.size().width(), screen.size().height())
        lay = QVBoxLayout(win._ss_dlg)
        lbl = QLabel()
        lbl.setPixmap(pix)
        lay.addWidget(lbl)
        win._ss_rb = QRubberBand(QRubberBand.Rectangle, lbl)
        def mousePress(e):
            win._ss_origin = e.pos()
            win._ss_rb.setGeometry(QRect(win._ss_origin, QPoint()))
            win._ss_rb.show()
        def mouseMove(e):
            win._ss_rb.setGeometry(QRect(win._ss_origin, e.pos()).normalized())
        def mouseRelease(e):
            rect = win._ss_rb.geometry()
            if rect.width() > 10 and rect.height() > 10:
                cropped = win._ss_pix.copy(rect)
                from datetime import datetime
                fn = os.path.join(win.base, r"data\截图_%s.png") % datetime.now().strftime("%Y%m%d_%H%M%S")
                cropped.save(fn)
                QMessageBox.information(win, "截图", "已保存:\n" + fn)
            win._ss_dlg.close()
        lbl.mousePressEvent = mousePress
        lbl.mouseMoveEvent = mouseMove
        lbl.mouseReleaseEvent = mouseRelease
        win._ss_dlg.showFullScreen()

    # 导出和截图移到 +号菜单里
    main.addLayout(top)

    # 主体：左侧边栏 + 右侧聊天
    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)
    sidebar_w = QWidget()
    sidebar_w.setFixedWidth(220)
    sidebar_w.setStyleSheet("background:white;border-right:1px solid #e0e0e0;")
    sidebar = QVBoxLayout(sidebar_w)
    sidebar.setContentsMargins(10, 10, 10, 10)
    sidebar.setSpacing(8)
    new_btn = QPushButton("＋ 新建对话")
    new_btn.setToolTip("创建一个新的聊天对话")
    new_btn.setStyleSheet("""
        QPushButton { background:#4a9eff; color:white; border:none; padding:10px;
                      border-radius:12px; font-size:13px; text-align:left; }
        QPushButton:hover { background:#3a8eef; }
    """)
    def _new_session():
        win.account.new_session()
        win.chat.clear()
        win._refresh_session_list()
    new_btn.clicked.connect(_new_session)
    sidebar.addWidget(new_btn)
    sidebar.addWidget(QLabel("<span style='color:#888;font-size:11px;'>历史对话</span>"))
    win.session_list = QListWidget()
    win.session_list.setStyleSheet("""
        QListWidget { background:transparent; color:#333; border:none; font-size:13px; }
        QListWidget::item { padding:8px; border-radius:6px; }
        QListWidget::item:hover { background:#f0f0f0; }
        QListWidget::item:selected { background:#e3f2fd; color:#1976d2; }
    """)
    from PyQt5.QtWidgets import QListWidgetItem
    _it = QListWidgetItem("💬 默认对话")
    _it.setData(Qt.UserRole, "default")
    win.session_list.addItem(_it)
    win.session_list.itemClicked.connect(win._on_session_clicked)
    sidebar.addWidget(win.session_list, 1)

    # ---- 已安装模块自带的按钮（数据来自 modules_repo/manifest.json）----
    # 部署文档一直写着"带按钮的模块安装后自动在侧边栏加按钮"，派发函数
    # dialog_mixin._module_button_clicked 也早就写好了，只是没人接到界面上。
    try:
        from core.module_buttons import load_buttons
        _mod_btns = load_buttons(getattr(win, "base", None))
    except Exception:
        _mod_btns = []
    if _mod_btns:
        sidebar.addWidget(QLabel("<span style='color:#888;font-size:11px;'>模块</span>"))
        for _b in _mod_btns:
            _mb = QPushButton(_b["label"])
            _mb.setToolTip("打开模块：%s" % _b["title"])
            _mb.setStyleSheet("""
                QPushButton { background:transparent; color:#333; border:none; padding:10px;
                              border-radius:12px; font-size:13px; text-align:left; }
                QPushButton:hover { background:#f0f0f0; }
            """)
            _mb.clicked.connect(
                lambda _checked=False, _n=_b["name"], _a=_b["action"]:
                win._module_button_clicked(_n, _a))
            sidebar.addWidget(_mb)

    fc_btn = QPushButton("功能中心")
    fc_btn.setToolTip("打开功能中心：电脑控制、MCP市场、插件市场等")
    fc_btn.setStyleSheet("""
        QPushButton { background:transparent; color:#333; border:none; padding:10px;
                      border-radius:12px; font-size:13px; text-align:left; }
        QPushButton:hover { background:#f0f0f0; }
    """)
    fc_btn.clicked.connect(win.center_dialog)
    sidebar.addWidget(fc_btn)
    set_btn = QPushButton("设置")
    set_btn.setToolTip("打开设置：模型配置、界面、数据等")
    set_btn.setStyleSheet("""
        QPushButton { background:transparent; color:#333; border:none; padding:10px;
                      border-radius:12px; font-size:13px; text-align:left; }
        QPushButton:hover { background:#f0f0f0; }
    """)
    set_btn.clicked.connect(win.set_dialog)
    sidebar.addWidget(set_btn)
    bottom_row = QHBoxLayout()
    bottom_row.setSpacing(6)
    win.login_btn_sb = QPushButton("🔑 登录")
    win.login_btn_sb.setStyleSheet("""
        QPushButton { background:#f5f5f5; color:#333; border:1px solid #ddd; padding:8px;
                      border-radius:6px; font-size:12px; }
        QPushButton:hover { background:#e8e8e8; }
    """)
    win.login_btn_sb.clicked.connect(win.show_login)
    bottom_row.addWidget(win.login_btn_sb)
    win.clear_btn_sb = QPushButton("🗑")
    win.clear_btn_sb.setToolTip("清空聊天")
    win.clear_btn_sb.setStyleSheet("""
        QPushButton { background:#f5f5f5; color:#333; border:1px solid #ddd; padding:8px;
                      border-radius:6px; font-size:12px; }
        QPushButton:hover { background:#e8e8e8; }
    """)
    win.clear_btn_sb.clicked.connect(lambda: win.chat.clear())
    bottom_row.addWidget(win.clear_btn_sb)
    sidebar.addLayout(bottom_row)
    body.addWidget(sidebar_w)

    right = QVBoxLayout()
    from gui.chat_view import ChatView
    win.chat = ChatView(win, base_dir=win.base)
    win.chat.setContextMenuPolicy(Qt.CustomContextMenu)
    def _chat_menu(pos):
        menu = win.chat.createStandardContextMenu()
        menu.setStyleSheet("QMenu { background-color: white; color: black; border: 1px solid #ddd; } QMenu::item:selected { background-color: #e3f2fd; }")
        # 改中文
        for a in menu.actions():
            txt = a.text()
            if "Copy" in txt: a.setText("复制")
            elif "Paste" in txt: a.setText("粘贴")
            elif "Cut" in txt: a.setText("剪切")
            elif "Undo" in txt: a.setText("撤销")
            elif "Redo" in txt: a.setText("重做")
            elif "Select All" in txt: a.setText("全选")
        sel = win.chat.textCursor().selectedText().strip()
        if sel:
            cite = menu.addAction("💬 引用选中文本")
            cite.triggered.connect(lambda: win.input.insert("【引用】" + sel[:200] + "\n"))
            cite.triggered.connect(lambda: win.input.insert("【引用】" + sel[:200] + "\n"))
            trans = menu.addAction("翻译成中文")
            def _do_translate():
                from PyQt5.QtWidgets import QMessageBox
                try:
                    tr = win.trunk._load_lazy("translate")
                    if tr:
                        r = tr.run(sel)
                        QMessageBox.information(win, "翻译结果", str(r)[:500])
                    else:
                        QMessageBox.information(win, "翻译", "翻译模块未加载")
                except Exception as e:
                    QMessageBox.warning(win, "翻译失败", str(e)[:120])
            trans.triggered.connect(_do_translate)
            trans = menu.addAction("翻译成中文")
            def _do_translate():
                from PyQt5.QtWidgets import QMessageBox
                try:
                    tr = win.trunk._load_lazy("translate")
                    if tr:
                        r = tr.run(sel)
                        QMessageBox.information(win, "翻译结果", str(r)[:500])
                    else:
                        QMessageBox.information(win, "翻译", "翻译模块未加载")
                except Exception as e:
                    QMessageBox.warning(win, "翻译失败", str(e)[:120])
            trans.triggered.connect(_do_translate)
    win.chat.customContextMenuRequested.connect(_chat_menu)
    win.chat.setReadOnly(True)
    win.chat.setOpenLinks(False)
    # anchorClicked 由 ChatView 内部处理，已删除手写 connect
    right.addWidget(win.chat, 1)
    try:
        _fs = int(win.trunk.config.get("font_size", "16px").replace("px", ""))
        win.chat.setStyleSheet("""
            font-size:%dpx;
            background-color: #f5f5f5;
            border: none;
            border-radius: 8px;
            padding: 10px;
        """ % _fs)
    except: pass

    input_frame = QFrame()
    input_frame.setStyleSheet("QFrame { border:1px solid #ddd; border-radius:12px; background:white; }")
    fl = QVBoxLayout(input_frame)
    fl.setContentsMargins(12, 10, 12, 8)
    fl.setSpacing(6)
    win.input = QTextEdit()
    win.input.setAcceptDrops(True)
    win.input.installEventFilter(win)
    win.input.setPlaceholderText("输入消息...（Enter 发送，Shift+Enter 换行）")
    win.input.setMinimumHeight(60)
    win.input.setMaximumHeight(120)
    win.input.setStyleSheet("border:none; background:transparent; font-size:14px;")
    win.input.installEventFilter(win)
    win.input.setContextMenuPolicy(Qt.CustomContextMenu)
    def _input_menu(pos):
        menu = win.input.createStandardContextMenu()
        menu.setStyleSheet("QMenu { background-color: white; color: black; border: 1px solid #ddd; } QMenu::item:selected { background-color: #e3f2fd; }")
        for a in menu.actions():
            txt = a.text()
            if "Copy" in txt: a.setText("复制")
            elif "Paste" in txt: a.setText("粘贴")
            elif "Cut" in txt: a.setText("剪切")
            elif "Undo" in txt: a.setText("撤销")
            elif "Redo" in txt: a.setText("重做")
            elif "Select All" in txt: a.setText("全选")
        menu.exec_(win.input.mapToGlobal(pos))
    win.input.customContextMenuRequested.connect(_input_menu)
    fl.addWidget(win.input)
    btn_row = QHBoxLayout()
    btn_row.setContentsMargins(0, 0, 0, 0)
    btn_row.setSpacing(4)
    # +号附件菜单
    win._auto_tts = win.trunk.config.get("auto_tts", False)
    win.plus_btn = QPushButton("+")
    win.plus_btn.setFixedSize(40, 30)
    win.plus_btn.setToolTip("附件")
    win.plus_btn.setStyleSheet("QPushButton{background:#4a9eff;color:white;border:none;border-radius:6px;font-size:18px;font-weight:bold;}QPushButton:hover{background:#3a8eef;}")
    def _show_plus_menu():
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(win)
        a1 = menu.addAction("上传文件")
        a2 = menu.addAction("送编辑器")
        a4 = menu.addAction("区域截图")
        a5 = menu.addAction("导出聊天记录")
        a_auto_tts = menu.addAction("自动朗读开关")
        a_ocr = menu.addAction("截图识字")
        action = menu.exec_(win.plus_btn.mapToGlobal(win.plus_btn.rect().bottomLeft()))
        if action == a1: win.upload_file()
        elif action == a2: win.send_last_code_to_editor()
        elif action == a4: do_screenshot()
        elif action == a5: do_export()
        elif action == a_auto_tts:
            win._auto_tts = not getattr(win, "_auto_tts", False)
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(win, "自动朗读", "自动朗读已" + ("开启" if win._auto_tts else "关闭"))
        elif action == a_ocr:
            win.chat.append_user("（截图识字功能开发中）")
    win.plus_btn.clicked.connect(_show_plus_menu)
    btn_row.addWidget(win.plus_btn)
    # 语音按钮
    win.voice_btn = QPushButton("语音输入")
    win.voice_btn.setFixedHeight(30)
    win.voice_btn.setStyleSheet("background:#f0f0f0;border:none;border-radius:6px;padding:0 10px;")
    win.voice_btn.clicked.connect(win._voice_btn_clicked)
    btn_row.addWidget(win.voice_btn)
    # 实时对话按钮
    win.realtime_btn = QPushButton("实时对话")
    win.realtime_btn.setFixedHeight(30)
    win.realtime_btn.setStyleSheet("background:#f0f0f0;border:none;border-radius:6px;padding:0 10px;")
    def _rt_toggle():
        rc = win.trunk._load_lazy("realtime_chat")
        if not rc: return
        st = rc.status()
        if st.get("运行中"):
            rc.stop()
            win.realtime_btn.setText("实时对话")
            win.realtime_btn.setStyleSheet("background:#f0f0f0;border:none;border-radius:6px;padding:0 10px;")
        else:
            r = rc.start()
            if r.get("ok"):
                win.realtime_btn.setText("录音中...")
                win.realtime_btn.setStyleSheet("background:#ff5252;color:white;border:none;border-radius:6px;padding:0 10px;")
    win.realtime_btn.clicked.connect(_rt_toggle)
    btn_row.addWidget(win.realtime_btn)
    # 本地/云端指示灯放到状态栏
    win.local_light = QLabel("●本地")
    win.local_light.setStyleSheet("color:#0f0;font-size:11px;padding:0 10px;")
    win.cloud_light = QLabel("●云端")
    win.cloud_light.setStyleSheet("color:#999;font-size:11px;padding:0 10px;")
    # 别名，兼容 dialog_mixin / settings_dialog
    win._status_local = win.local_light
    win._status_cloud = win.cloud_light
    win.model_btn = QPushButton("模型:本地路由")
    win.model_btn.setFixedHeight(28)
    win.model_btn.setStyleSheet("font-size:11px;padding:2px 8px;background:#f0f0f0;border:none;border-radius:6px;")
    win.model_btn.clicked.connect(win.switch_model)
    btn_row.addWidget(win.model_btn)
    btn_row.addStretch()
    win.editor_btn = QPushButton("代码编辑器")
    win.editor_btn.setFixedHeight(30)
    win.editor_btn.setStyleSheet("font-size:12px;padding:0 10px;background:#f0f0f0;border:none;border-radius:6px;")
    win.editor_btn.clicked.connect(win.open_code_editor)
    btn_row.addWidget(win.editor_btn)
    send = QPushButton("发送")
    send.setFixedSize(64, 30)
    send.setStyleSheet("QPushButton{background:#4a9eff;color:white;border:none;border-radius:6px;font-size:13px;font-weight:bold;}QPushButton:hover{background:#3a8eef;}QPushButton:pressed{background:#2a7edf;}")
    send.clicked.connect(win.send)
    btn_row.addWidget(send)
    fl.addLayout(btn_row)
    right.addWidget(input_frame)
    body.addLayout(right, stretch=1)
    main.addLayout(body)





