# -*- coding: utf-8 -*-
"""日志中心窗口 - 系统/错误/操作记录"""
import os, subprocess
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                             QTabWidget, QLineEdit, QComboBox)

from gui.feedback_states import make_action_links


def show_log_dialog(parent, dlg, base, import_data):
    """日志中心窗口

    原来还收 export_logs / export_data 两个回调（对应「导出日志包」「导出数据」
    两个按钮）。那两个按钮已撤 —— 它们是**重复入口**，同一能力已经在能力注册表里：
        crash_export   打包日志+配置+系统信息（密钥自动脱敏）
        migrate_export 把整份数据打包，换电脑时用
    命令面板（Ctrl+K）搜"导出"就能找到，而且那边是唯一实现。
    """
    d, l = dlg("📋 日志中心", w=720, h=560)

    head = QHBoxLayout()
    info = QLabel("正在读取日志...")
    info.setStyleSheet("color:#475569;font-size:12px;")
    head.addWidget(info, stretch=1)
    refresh_btn = QPushButton("🔄 刷新")
    refresh_btn.setStyleSheet("padding:5px 14px;")
    head.addWidget(refresh_btn)
    l.addLayout(head)

    # D2（功能深化二期）：关键词过滤 + 只看警告/错误
    frow = QHBoxLayout()
    filter_edit = QLineEdit()
    filter_edit.setPlaceholderText("过滤关键词（留空=全部）")
    filter_edit.setClearButtonEnabled(True)
    frow.addWidget(filter_edit, stretch=2)
    level_box = QComboBox()
    level_box.addItems(["全部", "只看 警告/错误"])
    frow.addWidget(level_box)
    l.addLayout(frow)

    tabs = QTabWidget()
    l.addWidget(tabs, stretch=1)

    def _read_file(path, tail=300):
        """读日志尾部 N 行，并返回文件总行数

        为什么要改成"读尾部"而不是 readlines() 全读：
            `lines = f.readlines()` 会把**整个文件**读进内存再切片，
            即使只显示最后 300 行。trunk.log 以前没有轮转（已修），
            但即便有轮转、阈值 10MB，全读也是 10MB 进内存 + 一次全文解码；
            如果日志被别的东西撑到几百 MB，打开日志中心就会卡住甚至爆内存。
        现在用 deque(maxlen=tail) 边读边丢，内存恒定只有 tail 行。
        总行数仍然数（用户要看"日志多少行"），但只做计数不存内容。
        """
        import collections
        try:
            if not os.path.exists(path):
                return "（文件不存在: %s）" % path, 0
            for enc in ("utf-8", "gbk", None):
                try:
                    kw = {"encoding": enc} if enc else \
                        {"encoding": "utf-8", "errors": "replace"}
                    buf = collections.deque(maxlen=tail)
                    total = 0
                    with open(path, **kw) as f:
                        for line in f:
                            buf.append(line)
                            total += 1
                    return "".join(buf), total
                except (UnicodeDecodeError, LookupError):
                    continue
            return "读取失败: 编码不认识", 0
        except Exception as e:
            return "读取失败: " + str(e)[:80], 0

    _ERR_TOKENS = ("error", "warn", "错误", "警告", "traceback",
                   "exception", "critical")

    def _filter_text(text):
        """按关键词/级别过滤日志文本（D2）。"""
        kw = filter_edit.text().strip().lower()
        lines = text.splitlines()
        out = []
        for ln in lines:
            low = ln.lower()
            if kw and kw not in low:
                continue
            if level_box.currentIndex() == 1 \
                    and not any(t in low for t in _ERR_TOKENS):
                continue
            out.append(ln)
        return "\n".join(out)

    sys_tb = QTextBrowser()
    sys_tb.setReadOnly(True)
    sys_tb.setLineWrapMode(QTextBrowser.NoWrap)
    tabs.addTab(sys_tb, "🟢 系统日志")

    err_tb = QTextBrowser()
    err_tb.setReadOnly(True)
    err_tb.setLineWrapMode(QTextBrowser.NoWrap)
    tabs.addTab(err_tb, "🔴 错误日志")

    op_tb = QTextBrowser()
    op_tb.setReadOnly(True)
    op_tb.setLineWrapMode(QTextBrowser.NoWrap)
    tabs.addTab(op_tb, "📝 操作记录")

    def _refresh():
        try:
            sp = os.path.join(base, "data", "logs", "trunk.log")
            txt, n1 = _read_file(sp, 300)
            sys_tb.setPlainText(_filter_text(txt))

            p1 = os.path.join(base, "data", "logs", "crashes.log")
            p2 = os.path.join(base, "data", "logs", "gui_crashes.log")
            t1, n2 = _read_file(p1, 120)
            t2, n3 = _read_file(p2, 120)
            err_tb.setPlainText("── crashes.log（%d 行）──\n%s\n\n── gui_crashes.log（%d 行）──\n%s"
                                % (n2, _filter_text(t1), n3, _filter_text(t2)))

            # 操作记录读 chats.db 的 messages 表。
            # 原来读的是 data/chat_gui.jsonl —— 那是 v5 的聊天存储，现在
            # AccountManager 全部走 ChatStore(chats.db)，没有任何代码再写它，
            # 所以这个页签永远显示"操作记录文件不存在"。
            opf = os.path.join(base, "data", "chats.db")
            rows = []
            n4 = 0
            if os.path.exists(opf):
                try:
                    import sqlite3
                    con = sqlite3.connect(opf)
                    try:
                        n4 = con.execute("select count(*) from messages").fetchone()[0]
                        cur = con.execute(
                            "select role, text from "
                            "(select id, role, text from messages order by id desc limit 100) "
                            "order by id asc")
                        pend = None
                        for role, text in cur:
                            text = str(text or "")
                            if role == "user":
                                if pend:
                                    rows.append("👤 " + pend + "\n🤖 （无回复）\n---")
                                pend = text[:120]
                            else:
                                rows.append("👤 " + (pend or "") + "\n🤖 " + text[:200] + "\n---")
                                pend = None
                        if pend:
                            rows.append("👤 " + pend + "\n🤖 （无回复）\n---")
                    finally:
                        con.close()
                except Exception:
                    rows.append("（操作记录解析异常）")
                op_tb.setPlainText("\n".join(rows) if rows else "（暂无操作记录）")
            else:
                op_tb.setPlainText("（还没有聊天记录库）")
            info.setText("系统日志 %d 行 · 错误日志 %d+%d 行 · 操作记录 %d 条" % (n1, n2, n3, n4))
        except Exception as e:
            info.setText("读取失败: " + str(e)[:60])

    refresh_btn.clicked.connect(_refresh)
    filter_edit.textChanged.connect(_refresh)
    level_box.currentIndexChanged.connect(_refresh)

    bot = QHBoxLayout()
    def _clear():
        try:
            logs_dir = os.path.join(base, "data", "logs")
            for fn in ("trunk.log", "crashes.log", "gui_crashes.log"):
                fp = os.path.join(logs_dir, fn)
                if os.path.exists(fp):
                    open(fp, "w", encoding="utf-8").close()
            info.setText("✅ 日志文件已清空（重启后不再显示）")
            _refresh()
        except Exception as e:
            info.setText("清空失败: " + str(e)[:60])
    def _open_dir():
        pdir = os.path.join(base, "data", "logs")
        os.makedirs(pdir, exist_ok=True)
        try:
            subprocess.Popen(["explorer", pdir])
        except Exception as e:
            info.setText("打开失败: " + str(e)[:50])
    # 「📦 导出日志包」和「💾 导出数据」两个按钮已撤 —— 它们是**重复入口**：
    # 同一能力已经在能力注册表里，命令面板（Ctrl+K）搜"导出"就能找到：
    #     导出日志包  -> crash_export（打包日志+配置+系统信息，密钥自动脱敏）
    #     导出数据    -> migrate_export（把整份数据打包，换电脑时用）
    # 而且它们这里走的是本文件里的 export_logs / export_data 两个局部函数，
    # 和注册表那份实现是两套 —— 留着只会让同一件事有两个真相。
    # 「清空 / 打开目录 / 导入数据」也是低频兜底动作 → 统一做成链接，
    # 这一屏只留「刷新」一个按钮（按钮预算只许降不许升）。
    bot.addWidget(make_action_links([
        ("🧹 清空日志", _clear),
        ("📂 打开日志目录", _open_dir),
        ("📂 导入数据", import_data),
    ]))
    bot.addStretch(1)
    l.addLayout(bot)

    _refresh()
    d.exec_()
