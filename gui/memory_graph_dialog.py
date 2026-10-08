# -*- coding: utf-8 -*-
"""v26-3.1: 记忆图谱可视化 完整版"""
import os, json, math, random
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGraphicsView, QGraphicsScene,
                             QGraphicsEllipseItem, QGraphicsLineItem,
                             QGraphicsTextItem, QGraphicsItem, QInputDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPen, QBrush, QColor, QFont


class MemoryGraphDialog(QDialog):
    """记忆图谱：节点+连线+拖拽+搜索"""
    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("记忆图谱")
        self.setMinimumSize(900, 700)
        self._build_ui()
        self._build_graph()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("🕸 记忆图谱 - 节点可拖拽，大小=频次"))
        btn_search = QPushButton("搜索")
        btn_search.clicked.connect(self._search)
        top.addWidget(btn_search)
        btn = QPushButton("刷新")
        btn.clicked.connect(self._rebuild)
        top.addWidget(btn)
        layout.addLayout(top)
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        layout.addWidget(self.view)

    def _rebuild(self):
        self.scene.clear()
        self._build_graph()

    def _search(self):
        name, ok = QInputDialog.getText(self, "搜索节点", "输入节点名：")
        if ok and name:
            # 简单高亮：找匹配的节点
            for item in self.scene.items():
                if isinstance(item, QGraphicsTextItem) and name in item.toPlainText():
                    self.view.ensureVisible(item)
                    break

    def _build_graph(self):
        # 1. 读知识图谱三元组
        triples = []
        kg_path = os.path.join(self.trunk.base, "data", "graph.json")
        if os.path.exists(kg_path):
            try:
                d = json.load(open(kg_path, encoding="utf-8"))
                triples = d.get("三元组", []) if isinstance(d, dict) else d
            except Exception:
                pass

        # 2. 构建节点和边
        nodes = {}
        edges = []
        for t in triples[-200:]:
            s, p, o = t.get("s", ""), t.get("p", ""), t.get("o", "")
            if not s or not o:
                continue
            nodes.setdefault(s, {"count": 0})
            nodes.setdefault(o, {"count": 0})
            nodes[s]["count"] += 1
            nodes[o]["count"] += 1
            edges.append((s, o, p))

        n = len(nodes)
        if n == 0:
            self.scene.addText("暂无记忆数据，先聊几句就会生成图谱")
            return

        # 3. 环形布局 + 随机扰动
        R = 250
        positions = {}
        for i, name in enumerate(nodes.keys()):
            angle = 2 * math.pi * i / n
            x = R * math.cos(angle) + random.randint(-20, 20)
            y = R * math.sin(angle) + random.randint(-20, 20)
            positions[name] = (x, y)

        # 4. 画边
        pen = QPen(QColor("#94a3b8"))
        pen.setWidth(1)
        for s, o, p in edges:
            if s not in positions or o not in positions:
                continue
            x1, y1 = positions[s]
            x2, y2 = positions[o]
            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(pen)
            line.setZValue(1)
            self.scene.addItem(line)

        # 5. 画节点
        for name, (x, y) in positions.items():
            r = 6 + min(nodes[name]["count"], 15)
            ellipse = QGraphicsEllipseItem(x - r, y - r, 2 * r, 2 * r)
            # 频次高的用红色，普通用蓝色
            color = QColor("#ef4444") if nodes[name]["count"] > 5 else QColor("#4a9eff")
            ellipse.setBrush(QBrush(color))
            ellipse.setPen(QPen(Qt.white, 1))
            ellipse.setFlag(QGraphicsItem.ItemIsMovable)
            ellipse.setFlag(QGraphicsItem.ItemIsSelectable)
            ellipse.setToolTip("%s (出现%d次)" % (name, nodes[name]["count"]))
            ellipse.setZValue(2)
            self.scene.addItem(ellipse)
            # 文字标签
            text = QGraphicsTextItem(name[:12])
            text.setPos(x + r + 3, y - 8)
            text.setFont(QFont("Microsoft YaHei", 8))
            text.setZValue(3)
            self.scene.addItem(text)
