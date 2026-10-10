# -*- coding: utf-8 -*-
"""日志中心窗口 - 系统/错误/操作记录"""
import os, subprocess
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTextBrowser, QTabWidget)


def show_log_dialog(parent, dlg, base, export_logs, export_data, import_data):
    """日志中心窗口"""
    d, l = dlg("📋 日志中心", w=720, h=560)

    head = QHBoxLayout()
    info = QLabel("正在读取日志...")
    info.setStyleSheet("color:#475569;font-size:12px;")
    head.addWidget(info, stretch=1)
    refresh_btn = QPushButton("🔄 刷新")
    refresh_btn.setStyleSheet("padding:5px 14px;")
    head.addWidget(refresh_btn)
    l.addLayout(head)

    tabs = QTabWidget()
    l.addWidget(tabs, stretch=1)

    def _read_file(path, tail=300):
        try:
            if os.path.exists(path):
                for enc in ("utf-8", "gbk"):
                    try:
                        with open(path, encoding=enc) as f:
                            lines = f.readlines()
                        return "".join(lines[-tail:]), len(lines)
                    except (UnicodeDecodeError, LookupError):
                        continue
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                return "".join(lines[-tail:]), len(lines)
            return "（文件不存在: %s）" % path, 0
        except Exception as e:
            return "读取失败: " + str(e)[:80], 0

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
            sys_tb.setPlainText(txt)

            p1 = os.path.join(base, "data", "logs", "crashes.log")
            p2 = os.path.join(base, "data", "logs", "gui_crashes.log")
            t1, n2 = _read_file(p1, 120)
            t2, n3 = _read_file(p2, 120)
            err_tb.setPlainText("── crashes.log（%d 行）──\n%s\n\n── gui_crashes.log（%d 行）──\n%s"
                                % (n2, t1, n3, t2))

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

    bot = QHBoxLayout()
    clear_btn = QPushButton("🧹 清空日志")
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
    clear_btn.clicked.connect(_clear)
    open_btn = QPushButton("📂 打开日志目录")
    def _open_dir():
        pdir = os.path.join(base, "data", "logs")
        os.makedirs(pdir, exist_ok=True)
        try:
            subprocess.Popen(["explorer", pdir])
        except Exception as e:
            info.setText("打开失败: " + str(e)[:50])
    open_btn.clicked.connect(_open_dir)
    export_btn = QPushButton("📦 导出日志包")
    export_btn.clicked.connect(export_logs)
    data_exp = QPushButton("💾 导出数据")
    data_exp.clicked.connect(export_data)
    data_imp = QPushButton("📂 导入数据")
    data_imp.clicked.connect(import_data)
    bot.addWidget(clear_btn)
    bot.addWidget(export_btn)
    bot.addWidget(data_exp)
    bot.addWidget(data_imp)
    bot.addWidget(open_btn)
    bot.addStretch(1)
    l.addLayout(bot)

    _refresh()
    d.exec_()
