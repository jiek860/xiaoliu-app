# -*- coding: utf-8 -*-
"""底部「终端」页：常驻 shell + 可选的真 PTY（ConPTY）后端。

为什么单独一个文件
------------------
`ide_editor_shell.py` 已经顶到 600 行硬上限（`tools/check_file_sizes.py`），
终端这一块（ANSI 清洗、编码、shell 生命周期、PTY 适配）本来就是独立的一坨，
挪出来既让上层文件回到预算内，也方便单独测。

两种后端，对上层是同一套调用：

* **pipe**（默认，零依赖）：常驻 ``cmd.exe /q /k``，stdin/stdout 走管道。
  中文按 Windows OEM 代码页（936）编码，输出 UTF-8 优先、GBK/OEM 兜底。
* **pty**（可选，装了 ``pywinpty`` 才有）：ConPTY 真终端，能跑 python REPL、
  有 Tab 补全/颜色，中文输入不用管 OEM 代码页（ConPTY 内部转 Unicode）。

``PtyShellProcess`` 故意模仿 ``QProcess`` 的那几个方法（start/write/
readAllStandardOutput/state/kill/...），``TerminalMixin`` 就不用为两种后端
各写一套启动/退出逻辑。
"""
from __future__ import annotations

import locale
import os
import re
import sys
import threading

from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from core.diagnostics import swallowed as _x6_swallowed

# CSI（含颜色/光标定位）和 OSC（ConPTY 改窗口标题）都要清掉：
# 真终端输出是"屏幕画面"，直接塞进 QPlainTextEdit 只会剩一堆控制符。
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


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
    for enc in ("gbk", "gb18030", _shell_encoding()):
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


# ---------------------------------------------------------------- PTY 后端
def _load_winpty():
    """延迟导入：没装 pywinpty 时不能让整个模块 import 失败。"""
    import winpty
    return winpty


def pty_available():
    """当前环境能不能用 PTY（只在 Windows 且装了 pywinpty 时成立）。"""
    if not sys.platform.startswith("win"):
        return False
    try:
        _load_winpty()
        return True
    except Exception as e:  # 静默是故意的
        _x6_swallowed(__name__, e, "probe pywinpty")
        return False


class _Env(dict):
    """QProcessEnvironment 的极小替身：调用方只用 insert()。"""

    def insert(self, key, value):
        self[str(key)] = str(value)


class PtyShellProcess(QObject):
    """pywinpty 真终端；接口对齐 TerminalMixin 用到的 QProcess 子集。"""

    readyReadStandardOutput = pyqtSignal()
    finished = pyqtSignal(int, int)

    NotRunning = 0
    Running = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._thread = None
        self._buf = []
        self._lock = threading.Lock()
        self._alive = False
        self._cwd = ""
        self._env = _Env()
        self._error = ""
        self._exit_code = 0

    def processEnvironment(self):
        return _Env(self._env)

    def setProcessEnvironment(self, env):
        self._env = _Env(env or {})

    def setWorkingDirectory(self, path):
        self._cwd = str(path or "")

    def setProcessChannelMode(self, _mode):
        """PTY 只有一路输出，没有"合并通道"的说法。"""

    def state(self):
        return self.Running if self._alive else self.NotRunning

    def errorString(self):
        return self._error or "PTY 启动失败"

    def waitForStarted(self, _ms=3000):
        return self._alive

    def waitForBytesWritten(self, _ms=2000):
        return True

    def readAllStandardOutput(self):
        """返回 str（pywinpty 的 read 已经按 UTF-8 解好，不用再做 carry）。"""
        with self._lock:
            text = "".join(self._buf)
            self._buf = []
        return text

    def write(self, data):
        if self._proc is None or not self._alive:
            return 0
        if isinstance(data, (bytes, bytearray)):
            data = bytes(data).decode("utf-8", errors="replace")
        try:
            return int(self._proc.write(str(data)) or 0)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "pty write")
            return 0

    def start(self, program, arguments=None):
        argv = [program] + list(arguments or [])
        env = dict(os.environ)
        env.update(self._env)
        try:
            w = _load_winpty()
            kwargs = {
                "cwd": self._cwd or None,
                "env": env,
                "dimensions": (30, 120),
            }
            backend = getattr(getattr(w, "Backend", None), "ConPTY", None)
            if backend is not None:
                kwargs["backend"] = backend
            self._proc = w.PtyProcess.spawn(argv, **kwargs)
        except Exception as e:  # 静默是故意的
            self._error = str(e) or e.__class__.__name__
            self._proc = None
            self._alive = False
            return False
        self._alive = True
        self._thread = threading.Thread(
            target=self._reader, name="x6-pty-reader", daemon=True)
        self._thread.start()
        return True

    def _reader(self):
        """后台读 PTY：只碰缓冲区和信号，不碰任何控件。"""
        proc = self._proc
        while self._alive and proc is not None:
            try:
                chunk = proc.read(4096)
            except EOFError:
                break
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "pty read")
                break
            if not chunk:
                break
            with self._lock:
                self._buf.append(str(chunk))
            self.readyReadStandardOutput.emit()
        try:
            code = int(proc.exitstatus or 0) if proc is not None else 0
        except Exception:
            code = 0
        self._exit_code = code
        self._alive = False
        self.finished.emit(code, 0)

    def kill(self):
        self._alive = False
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate(force=True)
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "pty terminate")

    def waitForFinished(self, ms=1000):
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(max(0, int(ms)) / 1000.0)
        return not self._alive

    def exit_code(self):
        return self._exit_code


# ---------------------------------------------------------------- 终端 Mixin
class TerminalMixin(object):
    """给 BottomPanel 用的终端页：UI + 常驻 shell + 两套后端切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shell = None            # 常驻 shell（懒启动，见 _ensure_shell）
        self._shell_kind = None       # "pty"（pywinpty）或 "pipe"（QProcess）
        self._shell_killing = False   # 主动关闭时别再打印"已退出"
        self._shell_primed = True     # Windows 先丢掉旧提示符，见 _on_shell_output
        self._shell_carry = b""       # UTF-8 被截断的半个汉字
        self._shell_prompt = "@x6@"   # 自定义提示符（不能含 <>|，会被当重定向）

    # ---------------------------------------------------- 终端页 UI
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
        if low in ("exit", "quit"):
            self.shutdown()
            return
        if self._ensure_shell() is None:
            return      # _ensure_shell 已经把失败原因写到终端页
        # PTY 是"真人打字"，控制台自己会回显命令，再补一行 $ 就重复了
        if self._shell_kind != "pty":
            self._echo("$ " + cmd)
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
        """返回可用的 shell；没有就启动一个（cwd 跟随终端当前目录）。

        Windows 上装了 pywinpty 就走 ConPTY（真终端，能跑 python REPL、有 Tab
        补全），没装就退回管道模式 —— 两条路径对上层是同一套调用。
        """
        if self._shell_alive():
            return self._shell
        self._drop_shell()
        use_pty = sys.platform.startswith("win") and pty_available()
        p = PtyShellProcess(self) if use_pty else QProcess(self)
        env = p.processEnvironment()
        # 子进程（python 等）默认会按本地编码写管道，强制 UTF-8 才不乱码
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        if use_pty:
            # 用环境变量设提示符，省去再敲一次 prompt（PTY 会把命令回显出来）
            env.insert("PROMPT", self._shell_prompt)
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(self.cwd)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._on_shell_output)
        p.finished.connect(self._on_shell_done)
        self._shell_carry = b""
        if use_pty:
            p.start("cmd.exe", [])
        elif sys.platform.startswith("win"):
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
        self._shell_kind = "pty" if use_pty else "pipe"
        if sys.platform.startswith("win"):
            # 把提示符换成哨兵，输出里好剥掉；先缓冲，见到哨兵再开始显示
            self._shell_primed = False
            if not use_pty:
                self._write_shell("prompt " + self._shell_prompt)
            # ConPTY 启动要重画整屏，首屏输出比管道慢，给足 3 秒再兜底
            QTimer.singleShot(3000 if use_pty else 2000, self._prime_shell)
        else:
            self._shell_primed = True
        return p

    def _prime_shell(self):
        """兜底：等了一会还没见到哨兵就别再憋着（提示符可能设失败）。"""
        if self._shell_alive() and not self._shell_primed:
            self._shell_primed = True
            self._shell_carry = b""

    def _write_shell(self, cmd):
        """把一行命令写进 shell 的 stdin；cwd 同步也走这里。"""
        p = self._shell
        if p is None or p.state() == QProcess.NotRunning:
            return False
        if self._shell_kind == "pty":
            # ConPTY 收 UTF-8 再转成控制台 Unicode 输入，中文不用管 OEM 代码页
            try:
                p.write(cmd + "\r")
                return True
            except Exception as e:  # 静默是故意的
                _x6_swallowed(__name__, e, "pty terminal write")
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
            raw = p.readAllStandardOutput()
        except Exception as e:  # 静默是故意的
            _x6_swallowed(__name__, e, "terminal read")
            return
        if not raw:
            return
        if isinstance(raw, (bytes, bytearray)):
            text, self._shell_carry = _decode_shell_bytes(
                bytes(raw), self._shell_carry)
        else:
            # PTY 后端读出来已经是 str（pywinpty 内部按 UTF-8 解好了）
            text = str(raw)
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
        self._shell_kind = None
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
