# -*- coding: utf-8 -*-
"""代码编辑器控件：语法高亮、行号、补全和右键菜单。"""
from __future__ import annotations

import ast
import re

from PyQt5.QtCore import Qt, QPoint, QRect, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import (QFont, QTextCharFormat, QColor, QSyntaxHighlighter,
                         QTextDocument, QTextCursor, QPainter)
from PyQt5.QtWidgets import (QPlainTextEdit, QWidget, QCompleter, QTextEdit)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
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

class CodeEditWidget(QPlainTextEdit):
    askAssistantRequested = pyqtSignal(str)  # 把选中/全部代码发回聊天框
    syntaxErrorChanged = pyqtSignal(int)     # 当前文件语法错误数（0/1）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 11
        f = QFont("Consolas", self._font_size); f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tab_width = 4
        # 行号
        self._ln_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_ln_area_width)
        self.updateRequest.connect(self._update_ln_area)
        # minimap：右侧缩略图，默认开，可被工作台命令关闭
        self._minimap = _MiniMap(self)
        self._minimap_visible = True
        self.textChanged.connect(self._minimap.update)
        self.blockCountChanged.connect(lambda _n: self._minimap.update())
        self._update_ln_area_width(0)
        # 高亮
        self._hl = _PyHighlighter(self.document())
        # 补全
        self._completer = None
        self._setup_completer()
        # 实时语法错误
        self._err_timer = QTimer(self); self._err_timer.setSingleShot(True)
        self._err_timer.setInterval(400)
        self._err_timer.timeout.connect(self._check_syntax)
        self.textChanged.connect(self._err_timer.start)
        # 文件路径
        self._filepath = None
        self._dirty = False
        self._syntax_errors = 0
        self.document().modificationChanged.connect(
            lambda m: setattr(self, '_dirty', bool(m)))

    # ----- 属性 -----
    @property
    def filepath(self): return self._filepath
    @filepath.setter
    def filepath(self, v): self._filepath = v

    def is_dirty(self):
        # 文档状态才是唯一真相：setPlainText 会先发 modified=True 再复位，
        # 只信 _dirty 会误判"刚打开的文件未保存"。
        return bool(self._dirty or self.document().isModified())

    # ----- 行号 -----
    def line_number_area_width(self):
        n = max(1, self.blockCount())
        digits = len(str(n))
        return 20 + self.fontMetrics().horizontalAdvance('9') * digits

    def minimap_width(self):
        return _MiniMap.WIDTH if self._minimap_visible else 0

    def set_minimap_visible(self, on):
        self._minimap_visible = bool(on)
        self._minimap.setVisible(self._minimap_visible)
        self._update_ln_area_width(0)
        self._minimap.update()

    def is_minimap_visible(self):
        return self._minimap_visible

    def attach_document(self, doc):
        """分屏用：两个视图共享同一个 QTextDocument，改哪边都同步。"""
        try:
            self._hl.setDocument(None)
        except Exception as e:  # 静默是故意的 - 旧文档已失效时忽略
            _x6_swallowed(__name__, e, "detach highlighter")
        self._hl = None
        self.setDocument(doc)
        self._update_ln_area_width(0)
        self._minimap.update()

    def _update_ln_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0,
                                self.minimap_width(), 0)

    def _update_ln_area(self, rect, dy):
        if dy:
            self._ln_area.scroll(0, dy)
        else:
            self._ln_area.update(0, rect.y(), self._ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_ln_area_width(0)
        self._minimap.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._ln_area.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_area_width(), cr.height()))
        w = self.minimap_width()
        self._minimap.setGeometry(QRect(cr.right() - w + 1, cr.top(),
                                        w, cr.height()))

    def paint_line_numbers(self, e):
        """画行号。

        ⚠️ 这里曾两次出错，都是因为**把 Qt 的 API 想当然了**：
          ① 用 self.contentOffset()（QPlainTextEdit 自己才没有这个方法）；
          ② 用 self.viewport().contentOffset()（viewport 是普通 QWidget，
             也没有）—— 于是 paintEvent 每次抛 AttributeError，
             控制台刷屏、行号区不刷新，日志里就是
             "'QWidget' object has no attribute 'contentOffset'"。

        正确写法是：`self.contentOffset()` 直接返回偏移（它是
        QPlainTextEdit 的成员），`self.blockBoundingGeometry(block)`
        返回的已经是**视口坐标**，两者相加得到的就是屏幕上的位置。
        """
        try:
            p = QPainter(self._ln_area)
        except Exception:  # 极端情况下拿不到画笔就跳过这一帧  # 静默是故意的
            return
        try:
            p.fillRect(e.rect(), QColor("#f2f3f5"))
            h = self.fontMetrics().height()
            offset = self.contentOffset()
            block = self.firstVisibleBlock()
            bn = block.blockNumber()
            geom = self.blockBoundingGeometry(block).translated(offset)
            y = int(geom.top())
            p.setPen(QColor("#8a919c"))
            while block.isValid() and y <= e.rect().bottom():
                p.drawText(0, y, self._ln_area.width() - 6, h,
                           Qt.AlignRight, str(bn + 1))
                block = block.next()
                bn += 1
                if not block.isValid():
                    break
                y += int(self.blockBoundingRect(block).height())
        except Exception:  # 静默是故意的
            # 绘制期间的异常绝不能冒泡到 Qt 事件循环（会刷屏崩溃日志）
            pass
        finally:
            p.end()

    # ----- 补全 -----
    def _setup_completer(self):
        self._completer = QCompleter([], self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.activated.connect(self._insert_completion)

    def _insert_completion(self, s):
        # 删掉当前 word prefix，插入完整补全词
        prefix = self._completer.completionPrefix()
        tc = self.textCursor()
        for _ in range(len(prefix)):
            tc.deletePreviousChar()
        tc.insertText(s)
        self.setTextCursor(tc)

    def _try_complete(self):
        try:
            import jedi
        except Exception as e:
            _x6_swallowed(__name__, e)
            return
        code = self.toPlainText()
        cur = self.textCursor()
        line = cur.blockNumber() + 1
        col = cur.columnNumber()
        try:
            script = jedi.Script(code)
            comps = script.complete(line, col)
            words = [c.name for c in comps][:20]
            if not words:
                self._completer.popup().hide(); return
            self._completer.model().setStringList(words)
            prefix = self._word_under_cursor()
            self._completer.setCompletionPrefix(prefix)
            rect = self.cursorRect()
            rect.setWidth(self._completer.popup().sizeHintForColumn(0) + 20)
            self._completer.complete(rect)
        except Exception as e:
            _x6_swallowed(__name__, e)
            pass

    def _word_under_cursor(self):
        tc = self.textCursor()
        tc.select(QTextCursor.WordUnderCursor)
        return tc.selectedText()

    # ----- 键盘 -----
    def keyPressEvent(self, e):
        # Ctrl+滚轮缩放在 wheelEvent 处理
        if e.key() == Qt.Key_Tab:
            # Tab → 4 空格
            self.textCursor().insertText(" " * self.tab_width)
            return
        if e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter:
            # 自动缩进：继承上一行缩进
            tc = self.textCursor()
            tc.select(QTextCursor.BlockUnderCursor)
            line = tc.selectedText()
            import re
            m = re.match(r'^(\s*)', line)
            indent = m.group(1) if m else ""
            super().keyPressEvent(e)
            self.textCursor().insertText(indent)
            return
        if e.key() == Qt.Key_ParenRight and e.modifiers() & Qt.ControlModifier:
            self._try_complete(); return
        if e.key() == Qt.Key_Escape and self._completer.popup().isVisible():
            self._completer.popup().hide(); return
        super().keyPressEvent(e)
        # 点号后自动补全
        if e.text() == ".":
            QTimer.singleShot(0, self._try_complete)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y() / 120
            self._font_size = max(8, min(24, self._font_size + int(d)))
            f = self.font(); f.setPointSize(self._font_size); self.setFont(f)
            return
        super().wheelEvent(e)

    # ----- 实时语法检查 -----
    def _check_syntax(self):
        """实时语法检查；非 Python 文件不拿 ast 误判。"""
        extra = []
        count = 0
        if self._filepath and not str(self._filepath).lower().endswith(".py"):
            self.setExtraSelections([])
            self._emit_syntax_errors(0)
            return
        code = self.toPlainText()
        try:
            ast.parse(code)
        except SyntaxError as ex:
            count = 1
            fmt = QTextCharFormat()
            fmt.setUnderlineColor(QColor("#e51400"))
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            block = self.document().findBlockByNumber(max(0, (ex.lineno or 1) - 1))
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = QTextCursor(block)
                sel.format = fmt
                extra.append(sel)
        self.setExtraSelections(extra)
        self._emit_syntax_errors(count)

    def _emit_syntax_errors(self, count):
        count = int(count or 0)
        if count != self._syntax_errors:
            self._syntax_errors = count
            self.syntaxErrorChanged.emit(count)

    # ----- 右键菜单 -----
    def contextMenuEvent(self, e):
        m = self.createStandardContextMenu()
        m.setStyleSheet("QMenu { background-color: white; color: black; border: 1px solid #ddd; } QMenu::item:selected { background-color: #e3f2fd; }")
        # 改中文
        for a in m.actions():
            txt = a.text()
            if "Copy" in txt: a.setText("复制")
            elif "Paste" in txt: a.setText("粘贴")
            elif "Cut" in txt: a.setText("剪切")
            elif "Undo" in txt: a.setText("撤销")
            elif "Redo" in txt: a.setText("重做")
            elif "Select All" in txt: a.setText("全选")
        m.addSeparator()
        act_ask = m.addAction("🤖 问小6（选中代码）")
        act_comment = m.addAction("💬 注释/取消注释")
        act_run = m.addAction("▶ 运行此文件")
        act_agent = m.addAction(" 交给工作台 AI（当前文件/选区）")
        act = m.exec_(e.globalPos())
        if act == act_ask:
            txt = self.textCursor().selectedText() or self.toPlainText()
            self.askAssistantRequested.emit(txt)
        elif act == act_agent:
            win = self.window()
            if hasattr(win, 'agent_journey_from_editor'):
                win.agent_journey_from_editor()
        elif act == act_comment:
            self._toggle_comment()
        elif act == act_run:
            # 由外层主窗口处理
            win = self.window()
            if hasattr(win, 'run_current'):
                win.run_current()

    def _toggle_comment(self):
        tc = self.textCursor()
        # 简化：对选中的每一行加/去 #
        start = tc.selectionStart(); end = tc.selectionEnd()
        c = QTextCursor(self.document())
        c.setPosition(start)
        start_block = c.blockNumber()
        c.setPosition(end)
        end_block = c.blockNumber()
        c.beginEditBlock()
        for bn in range(start_block, end_block + 1):
            blk = self.document().findBlockByNumber(bn)
            txt = blk.text()
            if txt.lstrip().startswith("#"):
                # 去注释
                idx = txt.find("#")
                c2 = QTextCursor(blk); c2.setPosition(blk.position() + idx)
                c2.deleteChar()
            else:
                c2 = QTextCursor(blk); c2.movePosition(QTextCursor.StartOfBlock)
                c2.insertText("# ")
        c.endEditBlock()
