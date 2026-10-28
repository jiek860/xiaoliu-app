# -*- coding: utf-8 -*-
"""编辑器的小零件：语法高亮、行号区、minimap。

为什么单独一个文件
------------------
`code_editor_widget.py` 在批次 35/36 加完静态检查与补全后接近 600 行
（`tools/check_file_sizes.py` 的硬上限），把这三个"只依赖 QWidget"的
零件搬出来，主控件只留编辑行为。

旧导入路径仍然可用：`from gui.code_editor_widget import _PyHighlighter`
（主控件 re-export 这里的名字，只搬代码不改行为）。
"""
from __future__ import annotations

import re

from PyQt5.QtCore import QPoint, QSize, Qt
from PyQt5.QtGui import (QColor, QFont, QPainter, QSyntaxHighlighter,
                         QTextCharFormat, QTextCursor, QTextDocument)
from PyQt5.QtWidgets import QWidget

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


class _PyHighlighter(QSyntaxHighlighter):
    KEYWORDS = ('False|None|True|and|as|assert|async|await|break|class|continue|'
                'def|del|elif|else|except|finally|for|from|global|if|import|in|is|'
                'lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|self')

    def __init__(self, doc: QTextDocument):
        super().__init__(doc)
        kw = QTextCharFormat(); kw.setForeground(QColor("#c586c0")); kw.setFontWeight(QFont.Bold)
        str_ = QTextCharFormat(); str_.setForeground(QColor("#ce9178"))
        com = QTextCharFormat(); com.setForeground(QColor("#6a9955"))
        num = QTextCharFormat(); num.setForeground(QColor("#b5cea8"))
        deco = QTextCharFormat(); deco.setForeground(QColor("#dcdcaa"))
        self._rules = [
            (r'\b(class|def)\b', kw),
            (r'@\w+', deco),
            (r'\b(%s)\b' % self.KEYWORDS, kw),
            (r'"[^"\\]*(\\.[^"\\]*)*"', str_),
            (r"'[^'\\]*(\\.[^'\\]*)*'", str_),
            (r'#[^\n]*', com),
            (r'\b\d+\.?\d*\b', num),
        ]

    def highlightBlock(self, text):
        for pat, fmt in self._rules:
            for m in re.finditer(pat, text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class _LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, e):
        self._editor.paint_line_numbers(e)


class _MiniMap(QWidget):
    """编辑器右侧的文档缩略图：按行密度画色块，点击跳转。

    取舍：不做语法着色、不画字符（大文件会卡），只用块长度映射宽度；
    一屏缩略图最多画 `height` 行，超出按步长抽样。
    """

    WIDTH = 76

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("minimap：点击跳转")
        self.setStyleSheet("background:#f6f8fa;")

    def paintEvent(self, _e):
        p = None
        try:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#f6f8fa"))
            doc = self._editor.document()
            n = doc.blockCount()
            if n <= 0 or self.height() <= 0:
                return
            scale = self.height() / float(n)
            step = max(1, int(1 / scale) if scale < 1 else 1)
            p.setPen(Qt.NoPen)
            for i in range(0, n, step):
                block = doc.findBlockByNumber(i)
                if not block.isValid():
                    break
                length = len(block.text())
                if not length:
                    continue
                p.fillRect(3, int(i * scale), min(
                    self.width() - 8, max(2, length // 2)),
                    max(1, int(step * scale)), QColor("#c9ced6"))
            self._paint_viewport(p, n)
        except Exception as e:  # 静默是故意的 - 缩略图异常不能影响编辑
            _x6_swallowed(__name__, e, "minimap paint")
        finally:
            if p is not None:
                p.end()

    def _paint_viewport(self, p, n):
        vp = self._editor.viewport()
        if vp.height() <= 0 or self.height() <= 0:
            return
        top = self._editor.cursorForPosition(QPoint(0, 0)).blockNumber()
        bottom = self._editor.cursorForPosition(
            QPoint(0, vp.height() - 1)).blockNumber()
        y = int(top * self.height() / float(n))
        h = max(6, int((bottom - top + 1) * self.height() / float(n)))
        p.fillRect(0, y, self.width(), h, QColor(29, 78, 216, 34))

    def _goto(self, y):
        doc = self._editor.document()
        n = max(1, doc.blockCount())
        line = max(0, min(n - 1, int(y * n / float(max(1, self.height())))))
        block = doc.findBlockByNumber(line)
        if block.isValid():
            self._editor.setTextCursor(QTextCursor(block))
            self._editor.centerCursor()

    def mousePressEvent(self, e):
        self._goto(e.pos().y())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._goto(e.pos().y())
