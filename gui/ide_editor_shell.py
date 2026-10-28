# -*- coding: utf-8 -*-
"""工作台编辑器外壳：标签栏 + 面包屑 + 编辑区、底部「输出/问题/终端」面板。

为什么不用 QTabWidget
--------------------
QTabWidget 把标签栏和内容区绑死，面包屑只能插在它上方（标签在下），
与 VS Code「标签在上、面包屑在下」相反。这里拆成
`QTabBar + 面包屑 + QStackedWidget`，对外仍暴露 QTabWidget 那套 API
（addTab/removeTab/widget/count/currentWidget/...），调用方不用改。

为什么单独一个文件
------------------
`code_editor_dialog.py` 已接近 600 行上限，标签栏 shim 和底部面板
都是纯 UI 零件，放这里更方便单独测试。

约束：不创建 QPushButton/QAction；页签是 QTabBar，动作走双击/回车。
"""
from __future__ import annotations

import locale
import os
import re
import sys

from PyQt5.QtCore import QProcess, QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (QLineEdit, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QSplitter, QStackedWidget,
                             QTabBar, QVBoxLayout, QWidget)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _clean_ansi(text):
    """去掉 ANSI 转义序列：QPlainTextEdit 不解析颜色，留着只会是乱码。"""
    return _ANSI_RE.sub("", str(text or ""))


def _decode_shell_bytes(data, carry=b""):
    """管道字节流解码：先 UTF-8，失败再按本地编码（中文 Windows 是 GBK）。

    UTF-8 失败且只是"结尾被截断"时，把尾部留给下一次 read —— 否则一个汉字
    被拆成两次读取就会变成 U+FFFD。
    """
    buf = bytes(carry) + bytes(data or b"")
    if not buf:
        return "", b""
    try:
        return buf.decode("utf-8"), b""
    except UnicodeDecodeError as e:
        if e.reason.startswith("unexpected end") and len(buf) - e.start <= 8:
            try:
                return buf[:e.start].decode("utf-8"), buf[e.start:]
            except UnicodeDecodeError:
                pass
    for enc in (_shell_encoding(), "gbk", "gb18030"):
        try:
            return buf.decode(enc), b""
        except (UnicodeDecodeError, LookupError):
            continue
    return buf.decode("utf-8", errors="replace"), b""


def _shell_encoding():
    """cmd.exe 读写管道用的是 Windows OEM 代码页（中文系统 936）。

    不能用 locale.getpreferredencoding(False)：Python 开了 UTF-8 模式后它恒为
    utf-8（本机 3.12 就是这样），拿它发中文会被 cmd 按 936 解成乱码。
    """
    if sys.platform.startswith("win"):
        try:
            import ctypes
            cp = int(ctypes.windll.kernel32.GetOEMCP())
            if cp > 0:
                return "utf-8" if cp == 65001 else "cp%d" % cp
        except Exception:      # 静默是故意的：拿不到就走下面的兜底
            pass
    try:
        return locale.getpreferredencoding(False) or "utf-8"
    except Exception:      # 静默是故意的：拿不到就用 UTF-8
        return "utf-8"


_TAB_QSS = (
    "QTabBar{background:#f6f8fa;}"
    "QTabBar::tab{background:#f6f8fa;color:#57606a;padding:4px 12px;"
    "border:1px solid #d0d7de;border-bottom:none;"
    "border-top-left-radius:5px;border-top-right-radius:5px;"
    "margin-right:2px;}"
    "QTabBar::tab:selected{background:#ffffff;color:#1f2328;}")


class EditorTabs(QWidget):
    """`QTabBar + 面包屑 + QStackedWidget`，兼容 QTabWidget 常用 API。

    header 会插在标签栏和内容区之间 —— 面包屑正好放这里。
    """

    currentChanged = pyqtSignal(int)
    tabCloseRequested = pyqtSignal(int)
    customContextMenuRequested = pyqtSignal(QPoint)

    def __init__(self, header=None, parent=None):
        super().__init__(parent)
        self.bar = QTabBar(self)
        self.bar.setDocumentMode(True)
        self.bar.setExpanding(False)
        self.bar.setMovable(True)
        self.bar.setElideMode(Qt.ElideRight)
        self.bar.setUsesScrollButtons(True)
        self.bar.setStyleSheet(_TAB_QSS)
        self.stack = QStackedWidget(self)
        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self.stack)
        self._secondary = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.bar)
        if header is not None:
            lay.addWidget(header)
        lay.addWidget(self._splitter, 1)
        self.bar.currentChanged.connect(self._on_bar_changed)
        self.bar.tabCloseRequested.connect(self.tabCloseRequested)
        self.bar.customContextMenuRequested.connect(
            self.customContextMenuRequested)

    # ---------------------------------------------------- QTabWidget 兼容
    def addTab(self, w, title):
        self.stack.addWidget(w)
        i = self.bar.addTab(str(title))
        if self.bar.count() == 1:
            self.stack.setCurrentIndex(0)
        self._align()
        return i

    def removeTab(self, i):
        if i < 0 or i >= self.stack.count():
            return
        w = self.stack.widget(i)
        self.stack.removeWidget(w)
        self.bar.removeTab(i)
        target = self.stack.currentIndex()
        if target < 0:
            target = 0 if self.stack.count() else -1
        if self.bar.count() and self.bar.currentIndex() != target:
            self.bar.setCurrentIndex(target)      # 触发 currentChanged
        else:
            self.stack.setCurrentIndex(target)
            self.currentChanged.emit(target)

    def widget(self, i):
        return self.stack.widget(i)

    def indexOf(self, w):
        return self.stack.indexOf(w)

    def count(self):
        return self.stack.count()

    def currentWidget(self):
        return self.stack.currentWidget()

    def currentIndex(self):
        return self.stack.currentIndex()

    def setCurrentIndex(self, i):
        if i < 0 or i >= self.bar.count():
            return
        self.bar.setCurrentIndex(i)               # 触发 currentChanged

    def setCurrentWidget(self, w):
        self.setCurrentIndex(self.indexOf(w))

    def setTabText(self, i, text):
        if 0 <= i < self.bar.count():
            self.bar.setTabText(i, str(text))

    def tabText(self, i):
        return self.bar.tabText(i) if 0 <= i < self.bar.count() else ""

    def setTabsClosable(self, on):
        self.bar.setTabsClosable(bool(on))

    def setDocumentMode(self, on):
        self.bar.setDocumentMode(bool(on))

    def setContextMenuPolicy(self, policy):
        self.bar.setContextMenuPolicy(policy)

    def mapToGlobal(self, pos):
        return self.bar.mapToGlobal(pos)

    def tabBar(self):
        return self.bar

    # ---------------------------------------------------- 分屏
    def set_secondary(self, w):
        """在编辑区右侧加第二个视图（分屏）。"""
        if w is None:
            return self.clear_secondary()
        if self._secondary is not None and self._secondary is not w:
            self._secondary.setParent(None)
        self._secondary = w
        self._splitter.addWidget(w)
        w.show()
        total = max(400, self.width())
        self._splitter.setSizes([total // 2, total // 2])
        return w

    def clear_secondary(self):
        w = self._secondary
        self._secondary = None
        if w is not None:
            w.setParent(None)
        self._splitter.setSizes([1, 0])
        return w

    def secondary(self):
        return self._secondary

    def has_secondary(self):
        return self._secondary is not None

    def _on_bar_changed(self, i):
        if 0 <= i < self.stack.count():
            self.stack.setCurrentIndex(i)
        self.currentChanged.emit(i)

    def _align(self):
        """标签和内容数量对齐时把两边索引同步一次。"""
        n = min(self.bar.count(), self.stack.count())
        if n and self.bar.currentIndex() != self.stack.currentIndex():
            self.stack.setCurrentIndex(max(0, self.bar.currentIndex()))


class BottomPanel(QWidget):
    """底部面板：输出（复用编辑器输出框） / 问题 / 终端。"""

    jumpRequested = pyqtSignal(int)

    def __init__(self, output, root=".", parent=None):
        super().__init__(parent)
        self.root = os.path.abspath(root or os.getcwd())
        self.cwd = self.root
        self._shell = None      # 常驻 shell（懒启动，见 _ensure_shell）
        self._shell_killing = False   # 主动关闭时别再打印"已退出"
        self._shell_primed = True     # Windows 先丢掉旧提示符，见 _on_shell_output
        self._shell_carry = b""       # UTF-8 被截断的半个汉字
        self._shell_prompt = "@x6@"   # 自定义提示符（不能含 <>|，会被当重定向）
        self.bar = QTabBar(self)
        self.bar.setDocumentMode(True)
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setStyleSheet(
            _TAB_QSS.replace("padding:4px 12px", "padding:3px 10px"))
        self.bar.addTab("输出")
        self.bar.addTab("问题")
        self.bar.addTab("终端")
        self.stack = QStackedWidget(self)
        self.stack.addWidget(output)
        self.problems = QListWidget()
        self.problems.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;font-size:11px;}"
            "QListWidget::item{padding:3px 8px;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.problems.itemDoubleClicked.connect(self._open_problem)
        self.stack.addWidget(self.problems)
        self.stack.addWidget(self._build_terminal())
        self.bar.addTab("差异")
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setStyleSheet(
            "background:#ffffff;color:#24292f;font-family:Consolas;"
            "font-size:12px;border:none;")
        self.stack.addWidget(self.diff)
        self.diff_index = self.bar.count() - 1
        self.bar.currentChanged.connect(self.stack.setCurrentIndex)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.bar)
        lay.addWidget(self.stack, 1)

    # ---------------------------------------------------- 终端页
    def _build_terminal(self):
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.term = QPlainTextEdit()
        self.term.setReadOnly(True)
        self.term.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas;"
            "font-size:12px;border:none;")
        self.term_input = QLineEdit()
        self.term_input.setPlaceholderText(
            "输入命令，Enter 执行（支持 cd / cls / pwd）")
        self.term_input.setStyleSheet(
            "QLineEdit{background:#252526;color:#d4d4d4;border:none;"
            "border-top:1px solid #3c3c3c;padding:3px 6px;"
            "font-family:Consolas;font-size:12px;}")
        self.term_input.returnPressed.connect(self.run_terminal)
        v.addWidget(self.term, 1)
        v.addWidget(self.term_input)
        return host

    def _echo(self, text):
        try:
            self.term.appendPlainText(str(text))
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal echo")

    def _append_raw(self, text):
        """流式追加：不自动补换行，且只在原本贴底时跟随滚动。"""
        if not text:
            return
        try:
            bar = self.term.verticalScrollBar()
            stick = bar.value() >= bar.maximum() - 4
            cur = self.term.textCursor()
            cur.movePosition(QTextCursor.End)
            if cur.columnNumber() > 0 and not text.startswith("\n"):
                text = "\n" + text      # 别和上一行（$ 命令回显）粘在一起
            self.term.setTextCursor(cur)
            self.term.insertPlainText(text)
            if stick:
                bar.setValue(bar.maximum())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal stream output")

    def run_terminal(self, text=None):
        """执行命令：cd / cls / pwd 本地处理，其余写进常驻 shell。"""
        cmd = (text if text is not None else self.term_input.text()).strip()
        if text is None:
            self.term_input.clear()
        if not cmd:
            # 空回车：shell 已退出就重启（"进程退出后回车自动重启"）
            if not self._shell_alive():
                self.select(2)
                self._ensure_shell()
            return
        low = cmd.casefold()
        if low in ("cls", "clear"):
            self.term.clear()
            return
        if low in ("pwd", "cd"):
            self._echo(self.cwd)
            return
        if low.startswith("cd "):
            self._change_dir(cmd.split(" ", 1)[1].strip())
            return
        self.select(2)
        self._echo("$ " + cmd)
        if low in ("exit", "quit"):
            self.shutdown()
            return
        if self._ensure_shell() is None:
            return      # _ensure_shell 已经把失败原因写到终端页
        self._write_shell(cmd)

    def _change_dir(self, arg):
        target = arg.strip().strip('"').strip("'")
        new = os.path.normpath(
            target if os.path.isabs(target) else os.path.join(self.cwd, target))
        if os.path.isdir(new):
            self.cwd = new
            self._echo(new)
            self._sync_shell_cwd()
        else:
            self._echo("目录不存在：%s" % target)

    # ---------------------------------------------------- 常驻 shell
    def _shell_alive(self):
        return self._shell is not None and self._shell.state() != QProcess.NotRunning

    def _ensure_shell(self):
        """返回可用的 shell；没有就启动一个（cwd 跟随终端当前目录）。"""
        if self._shell_alive():
            return self._shell
        self._drop_shell()
        p = QProcess(self)
        env = p.processEnvironment()
        # 子进程（python 等）默认会按本地编码写管道，强制 UTF-8 才不乱码
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(self.cwd)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._on_shell_output)
        p.finished.connect(self._on_shell_done)
        self._shell_carry = b""
        if sys.platform.startswith("win"):
            # 不用 /u，也不要 chcp 65001：实测 cp65001 下中文输入会被 cmd 当成
            # 未闭合的续行（输出 "More?" 后卡死）；默认管道编码下 UTF-8 反而正常。
            p.start("cmd.exe", ["/q", "/k"])
        else:
            p.start("/bin/sh", ["-i"])
        if not p.waitForStarted(3000):
            err = p.errorString()
            p.deleteLater()
            self._echo("终端启动失败：%s" % err)
            return None
        self._shell = p
        if sys.platform.startswith("win"):
            # 把提示符换成哨兵，输出里好剥掉；先缓冲，见到哨兵再开始显示
            self._shell_primed = False
            self._write_shell("prompt " + self._shell_prompt)
            QTimer.singleShot(2000, self._prime_shell)
        else:
            self._shell_primed = True
        return p

    def _prime_shell(self):
        """兜底：2 秒还没见到哨兵就别再憋着（提示符可能设失败）。"""
        if self._shell_alive() and not self._shell_primed:
            self._shell_primed = True
            self._shell_carry = b""

    def _write_shell(self, cmd):
        """把一行命令写进 shell 的 stdin；cwd 同步也走这里。"""
        p = self._shell
        if p is None or p.state() == QProcess.NotRunning:
            return False
        end = "\r\n" if sys.platform.startswith("win") else "\n"
        try:
            data = (cmd + end).encode(_shell_encoding())
        except (UnicodeEncodeError, LookupError):
            data = (cmd + end).encode("utf-8", errors="replace")
        try:
            p.write(data)
            p.waitForBytesWritten(2000)
            return True
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal write")
            return False

    def _sync_shell_cwd(self):
        """shell 里也切一次目录，保证 dir / python 用的是同一个 cwd。"""
        if not self._shell_alive():
            return
        if sys.platform.startswith("win"):
            self._write_shell('cd /d "%s"' % self.cwd.replace('"', '""'))
        else:
            self._write_shell("cd '%s'" % self.cwd.replace("'", "'\\''"))

    def _on_shell_output(self):
        p = self.sender()
        if p is None or p is not self._shell:
            return
        try:
            data = bytes(p.readAllStandardOutput())
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal read")
            return
        if not data:
            return
        text, self._shell_carry = _decode_shell_bytes(data, self._shell_carry)
        text = _clean_ansi(text).replace("\r\n", "\n").replace("\r", "\n")
        if not self._shell_primed:
            # 旧提示符 + 哨兵之前的输出都丢掉，从哨兵之后开始算真正的输出
            if self._shell_prompt not in text:
                return
            text = text.split(self._shell_prompt, 1)[1]
            self._shell_primed = True
        text = text.replace(self._shell_prompt, "")
        self._append_raw(text)

    def _on_shell_done(self, code, _status=None):
        p = self.sender()
        killing = self._shell_killing
        self._shell_killing = False
        if p is self._shell:
            self._shell = None
        try:
            p.deleteLater()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal cleanup")
        if not killing:
            self._echo("<<< shell 已退出（%d），按 Enter 重启" % int(code))

    def shutdown(self):
        """关闭工作台时调用：杀掉常驻 shell，别留孤儿进程。"""
        self._drop_shell()

    def _drop_shell(self):
        p = self._shell
        self._shell = None
        self._shell_primed = True
        self._shell_carry = b""
        if p is None:
            return
        self._shell_killing = True
        try:
            p.kill()
            p.waitForFinished(1000)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "kill terminal shell")
        try:
            p.deleteLater()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "delete terminal shell")

    # ---------------------------------------------------- 问题页
    def set_problems(self, items):
        """问题页：兼容 (行, 描述) 与 (行, 列, 规则码, 描述) 两种写法。"""
        items = list(items or [])
        self.problems.clear()
        for entry in items:
            entry = tuple(entry or ())
            if not entry:
                continue
            try:
                line = int(entry[0] or 1)
            except (TypeError, ValueError):
                continue
            if len(entry) >= 4:
                col = int(entry[1] or 1)
                code = str(entry[2] or "")
                msg = str(entry[3] or "")
                text = "第 %d 行:%d  %s  %s" % (line, col, code, msg[:120])
            else:
                col, code, msg = 1, "", str(entry[1] if len(entry) > 1 else "")
                text = "第 %d 行  %s" % (line, msg[:120])
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, line)
            item.setToolTip("第 %d 行:%d  %s\n%s" % (line, col, code, msg))
            self.problems.addItem(item)
        self.bar.setTabText(1, "问题 %d" % len(items) if items else "问题")

    def _open_problem(self, item):
        line = item.data(Qt.UserRole)
        if line is not None:
            self.jumpRequested.emit(int(line))

    # ---------------------------------------------------- 差异页
    def show_diff(self, rel, text):
        """把 git diff 文本按 +/- 着色后放进「差异」页并切过去。"""
        try:
            name = os.path.basename(str(rel or "")) or "diff"
            self.diff.clear()
            cursor = self.diff.textCursor()
            for line in str(text or "").splitlines():
                first = line[:1]
                color = {"+": "#1a7f37", "-": "#cf222e",
                         "@": "#6e7781"}.get(first, "#24292f")
                if line.startswith(("+++", "---")):
                    color = "#6e7781"
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                cursor.insertText(line + "\n", fmt)
            self.bar.setTabText(self.diff_index, "差异 %s" % name[:24])
            self.select(self.diff_index)
            return text or ""
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "show git diff")
            return ""

    # ---------------------------------------------------- 对外
    def select(self, index):
        if 0 <= index < self.bar.count():
            self.bar.setCurrentIndex(index)

    def current_index(self):
        return self.bar.currentIndex()
