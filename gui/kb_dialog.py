# -*- coding: utf-8 -*-
"""知识库窗口 - 搜索/分类列表/详情"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                             QTextBrowser, QListWidget, QTabWidget, QPushButton)


def show_kb_dialog(parent, dlg, trunk, safe_stop_workers):
    """知识库窗口"""
    d, l = dlg("知识库")
    d.setFixedSize(600, 500)
    l.addWidget(QLabel("🔍 搜索:"))
    s = QLineEdit()
    l.addWidget(s)
    kbres = QTextBrowser()
    kbres.setFixedHeight(150)
    kbres.setReadOnly(True)
    l.addWidget(kbres)
    tabs = QTabWidget()
    allw = QListWidget()
    docs = trunk.call("vector_store", "list_all") or []
    for doc in docs[-100:]:
        allw.addItem(doc.get("text", "")[:60])
    tabs.addTab(allw, "全部")
    chatw = QListWidget()
    for doc in docs[-100:]:
        if doc.get("tag") == "对话" or "对话" in str(doc.get("text", "")):
            chatw.addItem(doc.get("text", "")[:60])
    tabs.addTab(chatw, "对话")
    learnw = QListWidget()
    for doc in docs[-100:]:
        if "学习" in str(doc.get("text", "")) or doc.get("tag") == "学习":
            learnw.addItem(doc.get("text", "")[:60])
    tabs.addTab(learnw, "学习")
    l.addWidget(tabs)
    def show_detail(item):
        kbres.setPlainText(item.text())
    allw.itemClicked.connect(show_detail)
    chatw.itemClicked.connect(show_detail)
    learnw.itemClicked.connect(show_detail)
    s.textChanged.connect(lambda t: (allw.clear(), [allw.addItem(doc.get("text", "")[:60]) for doc in (trunk.call("vector_store", "search", t, top_k=20) or []) if t in doc.get("text", "")]))
    l.addWidget(QLabel("🧠 知识管理"))
    l.addWidget(QPushButton("知识图谱", clicked=lambda: kbres.setPlainText(str(trunk.call("knowledge_graph", "run")))))
    d.exec_()
    safe_stop_workers()
