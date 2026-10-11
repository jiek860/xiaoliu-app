# -*- coding: utf-8 -*-
"""CodeEditorDialog v2.0 - 小6内置完整版代码编辑器
布局：左文件树 | 右多标签编辑区 | 底运行输出 | 状态栏
功能：
  - 多标签 / 行号 / Python 语法高亮 / 字体缩放
  - Tab 转 4 空格 / 自动缩进 / 实时语法错误下划线
  - jedi 自动补全
  - 文件树浏览 / 双击打开
  - 运行（QProcess）/ AI 修复（多轮）/ 右键"问小6"发回聊天
"""
import os
import sys
import ast
import tempfile
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QTextEdit, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QTreeView, QFileSystemModel, QSplitter, QCompleter, QStatusBar
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QRect, QSize, QTimer
from PyQt5.QtGui import QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QTextDocument, QTextCursor, QPainter


# ============ Python 语法高亮 ============
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
        import re
        for pat, fmt in self._rules:
            for m in re.finditer(pat, text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ============ 行号区域 ============
class _LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, e):
        self._editor.paint_line_numbers(e)


# ============ 单标签编辑组件 ============
class CodeEditWidget(QPlainTextEdit):
    askAssistantRequested = pyqtSignal(str)  # 把选中/全部代码发回聊天框

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
        self.document().modificationChanged.connect(lambda _: setattr(self, '_dirty', True))

    # ----- 属性 -----
    @property
    def filepath(self): return self._filepath
    @filepath.setter
    def filepath(self, v): self._filepath = v

    def is_dirty(self): return self._dirty

    # ----- 行号 -----
    def line_number_area_width(self):
        n = max(1, self.blockCount())
        digits = len(str(n))
        return 20 + self.fontMetrics().horizontalAdvance('9') * digits

    def _update_ln_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_ln_area(self, rect, dy):
        if dy:
            self._ln_area.scroll(0, dy)
        else:
            self._ln_area.update(0, rect.y(), self._ln_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_ln_area_width(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._ln_area.setGeometry(QRect(cr.left(), cr.top(),
                                       self.line_number_area_width(), cr.height()))

    def paint_line_numbers(self, e):
        p = QPainter(self._ln_area)
        p.fillRect(e.rect(), QColor("#f2f3f5"))
        n = self.blockCount()
        h = self.fontMetrics().height()
        top = self.viewport().contentOffset().y()
        block = self.firstVisibleBlock()
        bn = block.blockNumber()
        geom = self.blockBoundingGeometry(block).translated(self.contentOffset())
        y = int(geom.top() - top)
        while block.isValid() and y <= e.rect().bottom():
            p.setPen(QColor("#8a919c"))
            p.drawText(0, y, self._ln_area.width() - 6, h,
                       Qt.AlignRight, str(bn + 1))
            block = block.next(); bn += 1
            y += self.blockBoundingRect(block).height() if block.isValid() else 0

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
        except Exception:
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
        except Exception:
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
        # 清旧错误标记
        extra = []
        code = self.toPlainText()
        try:
            ast.parse(code)
        except SyntaxError as ex:
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
        act = m.exec_(e.globalPos())
        if act == act_ask:
            txt = self.textCursor().selectedText() or self.toPlainText()
            self.askAssistantRequested.emit(txt)
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


# ============ 主窗口 ============
class CodeEditorDialog(QMainWindow):
    askAssistantRequested = pyqtSignal(str)  # 发回小6聊天框

    def __init__(self, trunk, parent=None):
        super().__init__(parent)
        self.trunk = trunk
        self.setWindowTitle("📝 代码编辑器")
        self.resize(1100, 760)
        self._ai_history = []  # 多轮修复历史
        self._build_ui()
        # 默认打开一个新文件
        self.new_tab()

    def _build_ui(self):
        # 中心 splitter：左文件树 | 右（tabs + 输出）
        splitter = QSplitter(Qt.Horizontal)
        # 左：文件树
        self.fs_model = QFileSystemModel()
        root = getattr(self.trunk, 'base', None) or os.getcwd()
        self.fs_model.setRootPath(root)
        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setRootIndex(self.fs_model.index(root))
        self.tree.setColumnWidth(0, 220)
        for i in (1, 2, 3):
            self.tree.hideColumn(i)
        self.tree.doubleClicked.connect(self._on_tree_dbl)
        # 换根按钮
        tree_panel = QWidget(); tl = QVBoxLayout(tree_panel); tl.setContentsMargins(4,4,4,4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("📂"))
        btn_root = QPushButton("换目录"); btn_root.clicked.connect(self._change_root)
        bar.addWidget(btn_root)
        tl.addLayout(bar); tl.addWidget(self.tree)
        splitter.addWidget(tree_panel)

        # 右：上 tabs / 下输出
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0)
        # 工具条
        tb = QHBoxLayout()
        for label, slot in [("📄 新建", self.new_tab), ("📂 打开", self.open_file),
                            ("💾 保存", self.save_file), ("💾 另存为", self.save_as),
                            ("▶ 运行", self.run_current),
                            ("🔧 AI 修复", self.ai_fix),
                            ("✕ 关闭", self.close)]:
            b = QPushButton(label); b.setStyleSheet("padding:4px 10px;")
            b.clicked.connect(slot); tb.addWidget(b)
        tb.addStretch(1)
        rv.addLayout(tb)

        self.tabs = QTabWidget(); self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        rv.addWidget(self.tabs, stretch=3)

        rv.addWidget(QLabel("📟 运行输出："))
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        self.output.setMaximumHeight(180)
        self.output.setStyleSheet("background:#1e1e1e;color:#d4d4d4;font-family:Consolas;font-size:12px;")
        rv.addWidget(self.output, stretch=1)
        splitter.addWidget(right)
        splitter.setSizes([260, 840])
        self.setCentralWidget(splitter)

        # 状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

    # ----- 文件树 -----
    def _change_root(self):
        d = QFileDialog.getExistingDirectory(self, "选择项目根目录")
        if d:
            self.fs_model.setRootPath(d)
            self.tree.setRootIndex(self.fs_model.index(d))

    def _on_tree_dbl(self, idx):
        path = self.fs_model.filePath(idx)
        if os.path.isfile(path):
            self.open_path(path)

    # ----- Tab 管理 -----
    def _new_edit(self):
        w = CodeEditWidget()
        w.askAssistantRequested.connect(self.askAssistantRequested.emit)
        return w

    def new_tab(self):
        w = self._new_edit()
        idx = self.tabs.addTab(w, "未保存")
        self.tabs.setCurrentIndex(idx)
        w.textChanged.connect(lambda: self._update_tab_title(w))

    def _update_tab_title(self, w):
        i = self.tabs.indexOf(w)
        if i < 0: return
        name = os.path.basename(w.filepath) if w.filepath else "未保存"
        if w.is_dirty():
            name = "● " + name
        self.tabs.setTabText(i, name)

    def _close_tab(self, i):
        w = self.tabs.widget(i)
        if w.is_dirty():
            r = QMessageBox.question(self, "未保存", "当前文件有改动，保存？",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Save:
                self._save_w(w)
            elif r == QMessageBox.Cancel:
                return
        self.tabs.removeTab(i)

    def _current_edit(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditWidget) else None

    # ----- 打开/保存 -----
    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开", "", "Python (*.py);;所有文件 (*.*)")
        if path: self.open_path(path)

    def open_path(self, path):
        # 已开则切过去
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, CodeEditWidget) and w.filepath == path:
                self.tabs.setCurrentIndex(i); return
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e)); return
        w = self._new_edit(); w.setPlainText(txt); w.filepath = path
        i = self.tabs.addTab(w, os.path.basename(path))
        self.tabs.setCurrentIndex(i)

    def save_file(self):
        w = self._current_edit()
        if w: self._save_w(w)

    def _save_w(self, w):
        path = w.filepath
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "保存", "untitled.py", "Python (*.py)")
            if not path: return
        try:
            open(path, "w", encoding="utf-8").write(w.toPlainText())
            w.filepath = path
            w._dirty = False
            self.statusBar().showMessage("已保存: " + path, 3000)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def save_as(self):
        w = self._current_edit()
        if not w: return
        path, _ = QFileDialog.getSaveFileName(self, "另存为", "untitled.py", "Python (*.py)")
        if path:
            try:
                open(path, "w", encoding="utf-8").write(w.toPlainText())
                w.filepath = path; w._dirty = False
            except Exception as e:
                QMessageBox.warning(self, "另存失败", str(e))

    # ----- 外部接口（兼容旧版）-----
    def set_code(self, code, title="未命名"):
        """聊天框把 AI 给的代码送进来：新起一个 tab"""
        w = self._new_edit(); w.setPlainText(code or "")
        i = self.tabs.addTab(w, title)
        self.tabs.setCurrentIndex(i)
        self.show(); self.raise_(); self.activateWindow()

    def current_code(self):
        w = self._current_edit()
        return w.toPlainText() if w else ""

    # ----- 运行 -----
    def run_current(self):
        w = self._current_edit()
        if not w: return
        code = w.toPlainText()
        if not code.strip(): return
        # 如果是已保存文件直接跑，否则临时文件
        if w.filepath and not w.is_dirty():
            target = w.filepath
        else:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
            tmp.write(code); tmp.close()
            target = tmp.name
        self.output.clear()
        self.output.appendPlainText(">>> 运行: " + target)
        if hasattr(self, "_proc") and self._proc is not None:
            try: self._proc.kill()
            except Exception: pass
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_out)
        self._proc.finished.connect(self._on_fin)
        self._proc.start(sys.executable.replace("pythonw.exe", "python.exe"), [target])

    def _on_out(self):
        try:
            data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
            self.output.appendPlainText(data.rstrip())
        except Exception: pass

    def _on_fin(self, code, status):
        self.output.appendPlainText("<<< 退出码: %d" % code)

    # ----- AI 修复（多轮）-----
    def ai_fix(self):
        w = self._current_edit()
        if not w: return
        code = w.toPlainText()
        err = self.output.toPlainText()
        self.output.appendPlainText("\n>>> 🤖 正在让 AI 分析并修复...")
        try:
            llm = self.trunk.modules.get("llm")
            if not llm:
                self.output.appendPlainText("[!] LLM 未连接"); return
            user_msg = (
                "下面是一段 Python 代码和它运行时的输出/错误。请找出 bug 并直接给出"
                "修复后的完整可运行代码，用 ```python``` 代码块包裹，不要解释。\n\n"
                "=== 代码 ===\n" + code +
                "\n\n=== 运行输出 ===\n" + (err[-2000:] if err else "(无输出)")
            )
            msgs = [{"role": "system",
                     "content": "你是 Python 修复专家，只输出修复后的完整代码块。"}]
            msgs.extend(self._ai_history)
            msgs.append({"role": "user", "content": user_msg})
            r = llm.chat(msgs)
            r = str(r or "")
            self._ai_history.append({"role": "user", "content": user_msg})
            self._ai_history.append({"role": "assistant", "content": r})
            import re
            m = re.search(r"```(?:python|py)?\n(.*?)```", r, re.DOTALL)
            if m:
                w.setPlainText(m.group(1))
                self.output.appendPlainText("[✓] AI 已替换为修复后的代码，点▶运行再试")
            else:
                self.output.appendPlainText("[AI 回复]\n" + r[:1500])
        except Exception as e:
            self.output.appendPlainText("[AI 修复失败] " + str(e))


