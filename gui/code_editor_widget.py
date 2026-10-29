# -*- coding: utf-8 -*-
"""代码编辑器控件：语法高亮、行号、补全和右键菜单。"""
from __future__ import annotations

import ast
import builtins
import json
import keyword
import os
import re
import shutil
import sys

from PyQt5.QtCore import Qt, QRect, QTimer, QProcess, pyqtSignal
from PyQt5.QtGui import QFont, QTextCharFormat, QColor, QTextCursor, QPainter
from PyQt5.QtWidgets import QPlainTextEdit, QCompleter, QTextEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None

# 高亮 / 行号 / minimap 搬到了 gui/editor_parts.py；
# 这里 re-export 保持旧导入路径（from gui.code_editor_widget import _PyHighlighter）
from core.code.completion import (complete_words, indexed_words, jedi_enabled,
                                  project_root, same_dir_words)
from gui.editor_parts import (  # noqa: F401,E402
    _LineNumberArea, _MiniMap, _PyHighlighter)


_RUFF_TIMEOUT_MS = 5000
_COMPLETE_DELAY_MS = 80          # 批次 47.2：键入后 80ms 再算候选
_MAX_COMPLETION_WORDS = 300


def ruff_command(path):
    """ruff 检查命令；没装 ruff 时退回 `python -m ruff`（失败会走 ast 兜底）。"""
    exe = shutil.which("ruff")
    base = [exe] if exe else [sys.executable, "-m", "ruff"]
    return base + ["check", "--output-format=json", "--quiet", "--", str(path)]


def parse_ruff_json(text):
    """ruff JSON → [(line, col, code, msg)]；不是合法 JSON 返回 None（走兜底）。"""
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") or {}
        try:
            rows.append((int(loc.get("row") or 1),
                         int(loc.get("column") or 1),
                         str(item.get("code") or ""),
                         str(item.get("message") or "")))
        except (TypeError, ValueError):
            continue
    return rows


def ast_problems(code):
    """兜底：没跑成 ruff 时只报语法错误（与实时下划线同源）。"""
    try:
        ast.parse(code or "")
    except SyntaxError as ex:
        return [(int(ex.lineno or 1), int(ex.offset or 1), "SyntaxError",
                 str(ex.msg or "语法错误"))]
    return []


# ---------------------------------------------------------------- 补全候选
_JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")
_PY_WORDS = tuple(keyword.kwlist) + tuple(
    n for n in dir(builtins) if not n.startswith("_"))
_JS_WORDS = (
    "function", "const", "let", "var", "class", "return", "if", "else",
    "for", "while", "import", "export", "from", "async", "await", "new",
    "this", "true", "false", "null", "undefined", "typeof", "instanceof",
    "interface", "type", "enum", "implements", "extends", "throw", "try",
    "catch", "finally", "switch", "case", "break", "continue", "default",
    "console", "document", "window", "Promise", "Array", "Object")
_JS_DEF_RE = re.compile(
    r"\b(?:function|class)\s+([A-Za-z_$][\w$]*)"
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)")


def python_symbols(code):
    """ast 提取本文件符号：def/class/import as/赋值目标。

    写到一半有语法错误时 ast 会整体失败，退回正则只看 def/class，
    避免"补全直接没有候选"。
    """
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return set(re.findall(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)",
                              code or "", re.M))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.add(node.id)
    return out


def js_symbols(code):
    """JS/TS 的轻量符号表：function/class/const/let/var 的名字。"""
    out = set()
    for m in _JS_DEF_RE.finditer(code or ""):
        out.add(m.group(1) or m.group(2))
    return out


def completion_words(code, path=""):
    """补全候选：语言关键字 + 内置名 + 本文件符号（jedi 关时的全部候选）。"""
    ext = os.path.splitext(str(path or "").lower())[1]
    if ext in _JS_EXT:
        return sorted(set(_JS_WORDS) | js_symbols(code))
    return sorted(set(_PY_WORDS) | python_symbols(code))


def local_symbols(code, path=""):
    """本文件符号（排序第一档）：复用同一套 ast / 正则解析。"""
    ext = os.path.splitext(str(path or "").lower())[1]
    if ext in _JS_EXT:
        return js_symbols(code)
    return python_symbols(code)


class CodeEditWidget(QPlainTextEdit):
    askAssistantRequested = pyqtSignal(str)  # 把选中/全部代码发回聊天框
    syntaxErrorChanged = pyqtSignal(int)     # 当前文件问题数（ruff 或 ast）
    problemsChanged = pyqtSignal(list)       # [(行, 列, 规则码, 描述)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 11
        f = QFont("Consolas", self._font_size); f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tab_width = 4
        self._problems = []          # 当前问题列表（ruff 或 ast）
        self._ruff_proc = None
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
        # 键入 2 个字符后 300ms 再算候选：每次按键都 ast.walk 大文件会卡
        self._complete_timer = QTimer(self)
        self._complete_timer.setSingleShot(True)
        self._complete_timer.setInterval(_COMPLETE_DELAY_MS)
        self._complete_timer.timeout.connect(self._try_complete)
        # 实时语法错误
        self._err_timer = QTimer(self); self._err_timer.setSingleShot(True)
        self._err_timer.setInterval(400)
        self._err_timer.timeout.connect(self._check_syntax)
        self.textChanged.connect(self._err_timer.start)
        # 文件路径
        self._filepath = None
        self.trunk = None            # 由 code_editor_dialog 挂上，读补全开关
        self._recent_words = []      # 最近用过的补全词（排序第二档）
        self._completion_source = ""
        self._dirty = False
        self._syntax_errors = 0
        self.document().modificationChanged.connect(self._on_modified)

    def _on_modified(self, flag): self._dirty = bool(flag)

    # ----- 属性 -----
    @property
    def filepath(self): return self._filepath
    @filepath.setter
    def filepath(self, v):
        self._filepath = v
        self.check_problems()   # 打开/保存后跑一次静态检查

    def problems(self):
        """当前问题列表 [(行, 列, 规则码, 描述)]。"""
        return list(self._problems)

    def is_dirty(self):
        # 文档状态是唯一真相；setPlainText 会先置 modified 再复位，别只信缓存
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
        self.document().modificationChanged.connect(self._on_modified)
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
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)

    def _insert_completion(self, s):
        # 删掉当前 word prefix，插入完整补全词
        prefix = self._completer.completionPrefix()
        tc = self.textCursor()
        for _ in range(len(prefix)):
            tc.deletePreviousChar()
        tc.insertText(s)
        self.setTextCursor(tc)
        self._remember_word(s)

    def _remember_word(self, word):
        """记住刚用过的补全词（近期编辑档），最多 200 个，新的排前面。"""
        w = str(word or "")
        if not w:
            return
        try:
            self._recent_words.remove(w)
        except ValueError:
            pass
        self._recent_words.insert(0, w)
        del self._recent_words[200:]

    def _completion_enabled(self):
        """只对 .py/.js/.ts 启用；未保存的新标签按 Python 处理。"""
        if not self._filepath:
            return True
        ext = os.path.splitext(str(self._filepath).lower())[1]
        return ext in ((".py", ".pyw") + _JS_EXT)

    def _in_comment_or_string(self):
        """粗略判断光标是否在注释/字符串里：注释符在光标前 / 引号奇偶。"""
        cur = self.textCursor()
        col = cur.columnNumber()
        line = cur.block().text()
        before = line[:col]
        for marker in ("#", "//"):
            pos = line.find(marker)
            if 0 <= pos < col:
                return True
        for quote in ('"""', "'''", '"', "'"):
            if before.count(quote) % 2:
                return True
        return False

    def _try_complete(self, force=False):
        """补全：关键字 + 本文件符号；``code_complete.jedi`` 开了再叠 jedi Top-5。"""
        try:
            if not self._completion_enabled() or self._in_comment_or_string():
                self._hide_completion()
                return
            prefix = self._word_under_cursor()
            if len(prefix) < 2 and not force:
                self._hide_completion()
                return
            text = self.toPlainText()
            cur = self.textCursor()
            result = complete_words(
                completion_words(text, self._filepath), text, self._filepath,
                cur.blockNumber() + 1, cur.columnNumber(), prefix=prefix,
                jedi=jedi_enabled(self.trunk),
                root=project_root(self.trunk, self._filepath),
                local=local_symbols(text, self._filepath),
                recent=self._recent_words,
                same_dir=same_dir_words(self._filepath),
                indexed=indexed_words(self.trunk),
                limit=_MAX_COMPLETION_WORDS)
            self._completion_source = str(result.get("source") or "local")
            self._completer.model().setStringList(result.get("words") or [])
            self._completer.setCompletionPrefix(prefix)
            if not self._completer.completionCount():
                self._hide_completion()
                return
            rect = self.cursorRect()
            rect.setWidth(self._completer.popup().sizeHintForColumn(0) + 20)
            self._completer.complete(rect)
        except Exception as e:  # 静默是故意的 - 补全失败不能影响输入
            _x6_swallowed(__name__, e, "completion popup")

    def _hide_completion(self):
        popup = self._completer.popup() if self._completer is not None else None
        if popup is not None:
            popup.hide()

    def _word_under_cursor(self):
        tc = self.textCursor()
        tc.select(QTextCursor.WordUnderCursor)
        return tc.selectedText()

    # ----- 键盘 -----
    def keyPressEvent(self, e):
        # Ctrl+滚轮缩放在 wheelEvent 处理
        if e.key() == Qt.Key_Space and e.modifiers() & Qt.ControlModifier:
            self._try_complete(force=True); return
        if e.key() == Qt.Key_Tab:
            # Tab → 4 空格
            self.textCursor().insertText(" " * self.tab_width)
            return
        if e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter:
            # 自动缩进：继承上一行缩进
            tc = self.textCursor()
            tc.select(QTextCursor.BlockUnderCursor)
            line = tc.selectedText()
            m = re.match(r'^(\s*)', line)
            indent = m.group(1) if m else ""
            super().keyPressEvent(e)
            self.textCursor().insertText(indent)
            return
        if e.key() == Qt.Key_ParenRight and e.modifiers() & Qt.ControlModifier:
            self._try_complete(force=True); return
        if e.key() == Qt.Key_Escape and self._completer.popup().isVisible():
            self._completer.popup().hide(); return
        super().keyPressEvent(e)
        # 键入字母/下划线/点号后 300ms 再算候选
        if e.text() and (e.text().isalnum() or e.text() in "_.$"):
            self._complete_timer.start()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            d = e.angleDelta().y() / 120
            self._font_size = max(8, min(24, self._font_size + int(d)))
            f = self.font(); f.setPointSize(self._font_size); self.setFont(f)
            return
        super().wheelEvent(e)

    # ----- 实时语法检查 -----
    def _check_syntax(self):
        """实时语法检查；非 Python 文件不拿 ast 误判。

        编辑中只做 ast（零成本）；ruff 结果只描述**已保存**的文件内容，
        所以一旦有未保存改动就退回 ast，避免"问题页 12 条、状态栏 0 条"。
        """
        extra = []
        if self._filepath and not str(self._filepath).lower().endswith(
                (".py", ".pyw")):
            self.setExtraSelections([])
            self._set_problems([])
            return
        problems = ast_problems(self.toPlainText())
        if problems:
            fmt = QTextCharFormat()
            fmt.setUnderlineColor(QColor("#e51400"))
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            block = self.document().findBlockByNumber(
                max(0, problems[0][0] - 1))
            if block.isValid():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = QTextCursor(block)
                sel.format = fmt
                extra.append(sel)
        self.setExtraSelections(extra)
        if self.is_dirty():
            self._problems = []
        self._set_problems(self._problems or problems)

    # ----- 静态检查（ruff 优先，ast 兜底） -----
    def check_problems(self):
        """打开/保存后跑一次 ruff（QProcess 后台，不卡主线程）。"""
        path = self._filepath
        if not path or not str(path).lower().endswith((".py", ".pyw")):
            self._set_problems([])
            return []
        if self._ruff_proc is not None:
            try:
                self._ruff_proc.kill()
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "kill old ruff")
            self._ruff_proc = None
        proc = QProcess(self)
        self._ruff_proc = proc
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.finished.connect(lambda _c, _s, p=proc: self._on_ruff_done(p))
        proc.errorOccurred.connect(lambda _e, p=proc: self._on_ruff_error(p))
        cmd = ruff_command(path)
        proc.start(cmd[0], cmd[1:])
        QTimer.singleShot(_RUFF_TIMEOUT_MS, lambda p=proc: self._on_ruff_timeout(p))
        return []

    def _on_ruff_done(self, proc):
        if proc is not self._ruff_proc:
            return
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        self._ruff_proc = None
        rows = parse_ruff_json(out)
        if rows is None:
            # 没装 ruff / 参数不被识别：退回 ast，不把 stderr 当成问题列表
            _x6_swallowed(__name__, err, "ruff unavailable")
            rows = self._ast_from_path()
        self._set_problems(rows)

    def _on_ruff_error(self, proc):
        if proc is not self._ruff_proc:
            return
        self._ruff_proc = None
        self._set_problems(self._ast_from_path())

    def _on_ruff_timeout(self, proc):
        if proc is not self._ruff_proc:
            return
        try:
            proc.kill()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "kill slow ruff")
        self._ruff_proc = None
        self._set_problems(self._ast_from_path())

    def _ast_from_path(self):
        try:
            with open(self._filepath, encoding="utf-8", errors="replace") as f:
                return ast_problems(f.read())
        except (OSError, TypeError):
            return ast_problems(self.toPlainText())

    def _set_problems(self, items):
        rows = []
        for row in items or []:
            try:
                rows.append((int(row[0]), int(row[1]), str(row[2]), str(row[3])))
            except (IndexError, TypeError, ValueError):
                continue
        self._problems = rows
        self._syntax_errors = len(rows)
        self.syntaxErrorChanged.emit(len(rows))
        self.problemsChanged.emit(list(rows))
        return rows

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
