# -*- coding: utf-8 -*-
"""知识图谱 - 三元组浏览/搜索/统计（GraphRAG 社区检索）

拆成两个入口：
* build_graph_view() —— 把图谱查看器做成一个 QWidget，供独立窗口
  （show_graph_dialog）和「知识库」里的「图谱」标签复用。
* show_graph_dialog() —— 独立窗口版（M5 后不再是注册表主入口，仍兼容历史调用）。
"""
import os, json, io
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QTextBrowser)

from gui.feedback_states import make_action_links


def build_graph_view(trunk, parent=None):
    """构建知识图谱查看器，返回 QWidget。"""
    w = QWidget()
    if parent is not None:
        w.setParent(parent)
    l = QVBoxLayout(w)
    top = QHBoxLayout()
    search = QLineEdit()
    search.setPlaceholderText("搜索 主体 / 关系 / 客体（输入后按回车）")
    top.addWidget(search, stretch=1)
    st = QLabel("")
    st.setStyleSheet("font-weight:bold;color:#1e40af;font-size:12px;")
    top.addWidget(st)
    l.addLayout(top)
    res = QTextBrowser()
    res.setReadOnly(True)
    l.addWidget(res, stretch=1)

    def show_rag(result):
        if not isinstance(result, dict):
            res.setPlainText(str(result))
            return
        if not result.get("ok"):
            err = result.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            res.setPlainText("GraphRAG 失败: " + str(msg or "未知错误"))
            return
        lines = []
        communities = result.get("relevant_communities") or []
        if communities:
            lines.append("相关社区（%d）：" % len(communities))
            for comm in communities:
                lines.append("  [%s] %s" % (comm.get("id", "?"),
                                        comm.get("summary", "")))
                nodes = comm.get("nodes") or []
                lines.append("    实体: " + "、".join(str(n) for n in nodes[:8]))
        triples = result.get("triples") or []
        if triples:
            lines.append("\n相关三元组（%d）：" % len(triples))
            for row in triples[:20]:
                lines.append("  %s --%s--> %s" % (row.get("s", ""),
                                              row.get("p", ""), row.get("o", "")))
        if not lines:
            lines.append(result.get("hint") or "没有匹配到社区或三元组")
        res.setPlainText("\n".join(lines))

    def build_rag():
        show_rag(trunk.call("graph_rag", "build"))

    def query_rag():
        q = search.text().strip()
        if not q:
            res.setPlainText("先在搜索框输入问题，再点「社区检索」")
            return
        show_rag(trunk.call("graph_rag", "query", q))

    rag_row = QHBoxLayout()
    l.addLayout(rag_row)
    rag_row.addWidget(make_action_links([
        ("🗂 重建社区摘要", build_rag),
        ("🔎 社区检索", query_rag),
    ]))
    rag_row.addStretch(1)

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
    search.returnPressed.connect(lambda: load(search.text().strip()))
    load()
    return w


def show_graph_dialog(parent, dlg, trunk):
    """知识图谱独立窗口（历史兼容入口）。"""
    d, l = dlg("🧠 知识图谱", w=780, h=620)
    l.addWidget(build_graph_view(trunk, parent=d))
    d.exec_()