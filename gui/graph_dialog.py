# -*- coding: utf-8 -*-
"""知识图谱窗口 - 三元组浏览/搜索/统计"""
import os, json, io
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser


def show_graph_dialog(parent, dlg, trunk):
    """知识图谱窗口"""
    d, l = dlg("🧠 知识图谱", w=780, h=620)
    top = QHBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText("搜索 主体 / 关系 / 客体...")
    top.addWidget(search, stretch=1)
    st = QLabel("")
    st.setStyleSheet("font-weight:bold;color:#1e40af;font-size:12px;")
    top.addWidget(st)
    sbtn = QPushButton("🔍 搜索")
    sbtn.setStyleSheet("padding:6px 14px;")
    top.addWidget(sbtn)
    l.addLayout(top)
    res = QTextBrowser()
    res.setReadOnly(True)
    l.addWidget(res, stretch=1)
    gpath = os.path.join(trunk.base, "data", "graph.json")
    def load(kw=""):
        try:
            data = json.load(io.open(gpath, encoding="utf-8"))
            tris = data.get("三元组", []) if isinstance(data, dict) else data
            if kw:
                tris = [t for t in tris if kw in str(t.get("s", "")) or kw in str(t.get("p", "")) or kw in str(t.get("o", ""))]
            today = sum(1 for t in tris if str(t.get("time", "")).startswith("2026-09-23"))
            st.setText("共 %d 条 · 今日 %d 条" % (len(tris), today))
            rows = []
            for t in tris[-80:][::-1]:
                s_, p_, o_, tm = t.get("s", ""), t.get("p", ""), t.get("o", ""), t.get("time", "")
                rows.append('<div style="margin:6px 0;"><b>%s</b> <span style="color:#4a9eff">→ %s →</span> <b>%s</b> <span style="color:#94a3b8;font-size:11px">[%s]</span></div>'
                            % (str(s_), str(p_), str(o_), str(tm)))
            res.setHtml('<div style="font-size:14px;">' + (''.join(rows) if rows else '<div style="color:#94a3b8">暂无三元组</div>') + '</div>')
        except Exception as e:
            res.setPlainText("读取失败: " + str(e)[:80])
    sbtn.clicked.connect(lambda: load(search.text().strip()))
    search.returnPressed.connect(lambda: load(search.text().strip()))
    load()
    d.exec_()
