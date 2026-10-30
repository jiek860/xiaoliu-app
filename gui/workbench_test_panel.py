# -*- coding: utf-8 -*-
"""工作台「测试」页：受影响测试 + 失败定位 + 只重跑失败。

为什么单独成文件
----------------
`code_editor_dialog.py` 贴着 600 行上限，测试闭环又涉及 QProcess 生命周期，
合进去既超行数也难测。这里把纯逻辑（选测、参数拼装、结果摘要）抽成函数，
面板只负责「点链接 -> 跑 pytest -> 双击失败跳行」。

为什么用 QProcess 而不是 subprocess.run
--------------------------------------
pytest 一轮几十秒，UI 线程不能等；QProcess 走事件循环，输出边跑边进文本框。
"""
from __future__ import annotations

import os
import sys
import time

from PyQt5.QtCore import QProcess, Qt, pyqtSignal
from PyQt5.QtWidgets import (QLabel, QListWidget, QListWidgetItem,
                             QPlainTextEdit, QVBoxLayout, QWidget)

from core.code import verify
from gui.feedback_states import make_action_links

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None

MAX_OUTPUT_LINES = 400


# ---------------------------------------------------------------- 纯函数
def changed_paths(dialog):
    """已打开标签里的 .py 文件 -> 相对根目录的路径（选测输入）。"""
    root = str(getattr(dialog, "root", "") or os.getcwd())
    out = []
    tabs = getattr(dialog, "tabs", None)
    for i in range(tabs.count() if tabs is not None else 0):
        w = tabs.widget(i)
        path = str(getattr(w, "filepath", "") or "")
        if not path.endswith(".py"):
            continue
        try:
            rel = os.path.relpath(path, root)
        except ValueError:  # Windows 跨盘符
            rel = path
        rel = rel.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if rel and rel not in out:
            out.append(rel)
    return out


def pytest_args(tests=None, failed=None):
    """拼 pytest 参数：只重跑失败优先于选测，都没有就是全量。"""
    args = ["-m", "pytest", "-q"]
    failed = [str(x) for x in (failed or []) if str(x).strip()]
    tests = [str(x) for x in (tests or []) if str(x).strip()]
    chosen = failed or tests
    if not chosen:
        return args
    if failed:
        args.append("-x")
    args.extend(chosen)
    return args


def failure_text(item):
    """失败定位的一行文字：``path:line  (symbol)``。"""
    item = item or {}
    text = "%s:%s" % (item.get("file") or "?", item.get("line") or 0)
    symbol = str(item.get("symbol") or "")
    return text + ("  (%s)" % symbol if symbol else "")


def summarize(code, failed, found):
    """一行摘要：退出码 + 失败用例数 + 定位命中数。"""
    if code == 0:
        return "测试通过"
    if code == 5:
        return "没有收集到测试"
    if code is None:
        return "测试未完成"
    text = "失败 %d 个用例" % len(failed or [])
    if found:
        text += "，定位 %d 处" % len(found)
    return text


# ---------------------------------------------------------------- 面板
class TestPanel(QWidget):
    """底部「测试」页：运行 / 选测 / 只重跑失败，双击失败跳行。"""

    __test__ = False      # 名字带 Test 前缀，别让 pytest 当测试类收集
    jumpTo = pyqtSignal(str, int)

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.root = str(getattr(dialog, "root", "") or os.getcwd())
        self.proc = None
        self._buffer = ""
        self._started = 0.0
        self._selected = []
        self.failed = []
        self.found = []
        self.changed_provider = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QLabel("测试：尚未运行（双击失败行可跳转）")
        self.title.setStyleSheet(
            "color:#57606a;font-size:11px;padding:3px 8px;"
            "background:#f6f8fa;border-bottom:1px solid #eaecf0;")
        lay.addWidget(self.title)
        links = make_action_links([
            ("受影响测试", self.select_related),
            ("运行选中", self.run_selected),
            ("运行全部", self.run_all),
            ("只重跑失败", self.rerun_failed),
            ("清空", self.clear),
        ])
        links.setStyleSheet("padding:2px 8px;background:#ffffff;")
        lay.addWidget(links)
        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{border:none;background:#ffffff;font-size:11px;}"
            "QListWidget::item{padding:3px 8px;}"
            "QListWidget::item:selected{background:#eef4ff;color:#1d4ed8;}")
        self.list.itemDoubleClicked.connect(self._activate)
        lay.addWidget(self.list, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(110)
        self.output.setStyleSheet(
            "background:#1e1e1e;color:#d4d4d4;font-family:Consolas;"
            "font-size:11px;border:none;")
        lay.addWidget(self.output)

    # ---------------------------------------------------- 数据来源
    def _changed(self):
        if callable(self.changed_provider):
            try:
                return list(self.changed_provider() or [])
            except Exception as e:  # 静默是故意的 - 选测输入失败退回空
                _x6_swallowed(__name__, e, "test panel changed paths")
        return changed_paths(self.dialog)

    def _index(self):
        trunk = getattr(self.dialog, "trunk", None)
        try:
            if hasattr(trunk, "get_workspace_index"):
                return trunk.get_workspace_index()
        except Exception as e:  # 静默是故意的 - 没索引就选不出测试
            _x6_swallowed(__name__, e, "test panel workspace index")
        return None

    def select_related(self):
        """按打开的文件反查受影响测试，列出来（双击运行单个）。"""
        rels = self._changed()
        tests = verify.select_tests(self._index(), rels)
        self._selected = list(tests)
        self.list.clear()
        for path in tests:
            item = QListWidgetItem("🧪 " + path)
            item.setData(Qt.UserRole, ("test", path))
            self.list.addItem(item)
        if tests:
            self.title.setText("受影响测试 %d 个（来源 %d 个文件）"
                               % (len(tests), len(rels)))
        else:
            self.title.setText("没有找到受影响测试（先打开改动过的 .py）")
        return tests

    # ---------------------------------------------------- 运行
    def run(self, tests=None, failed=None):
        """跑指定测试 / 失败用例；已在跑就不重复启动。"""
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            self.title.setText("测试正在跑，等这一轮结束")
            return False
        self.list.clear()
        self.output.clear()
        self._buffer = ""
        self.failed, self.found = [], []
        self._started = time.monotonic()
        args = pytest_args(tests=tests, failed=failed)
        tail = " ".join(args[3:])
        self.title.setText("运行中：pytest " + tail if tail else "运行中：pytest")
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.setWorkingDirectory(self.root)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        self.proc.setProcessEnvironment(_qenv(env))
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        exe = sys.executable.replace("pythonw.exe", "python.exe")
        self.proc.start(exe, args)
        return True

    def run_selected(self):
        if not self._selected:
            self._selected = self.select_related()
        if not self._selected:
            self.title.setText("没有可运行的测试，先点「受影响测试」")
            return False
        return self.run(self._selected)

    def run_all(self):
        return self.run(None)

    def rerun_failed(self):
        if not self.failed:
            self.title.setText("还没有失败用例；先跑一轮")
            return False
        return self.run(failed=self.failed)

    def clear(self):
        self.list.clear()
        self.output.clear()
        self._selected, self.failed, self.found = [], [], []
        self.title.setText("测试：尚未运行（双击失败行可跳转）")

    # ---------------------------------------------------- 进程回调
    def _read(self):
        try:
            self._buffer += bytes(
                self.proc.readAllStandardOutput()).decode(
                    "utf-8", errors="replace")
            lines = self._buffer.splitlines()
            if len(lines) > MAX_OUTPUT_LINES:
                self._buffer = "\n".join(lines[-MAX_OUTPUT_LINES:])
                lines = self._buffer.splitlines()
            self.output.setPlainText("\n".join(lines[-MAX_OUTPUT_LINES:]))
            bar = self.output.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception as e:  # 静默是故意的 - 输出读失败不影响测试
            _x6_swallowed(__name__, e, "test panel read output")

    def _done(self, code, _status):
        elapsed = time.monotonic() - self._started
        self._read()
        self.failed = verify.failed_test_ids(self._buffer)
        self.found = verify.locate_failures(self._buffer, None, self.root)
        self.list.clear()
        for item in self.found:
            row = QListWidgetItem("❌ " + failure_text(item))
            row.setData(Qt.UserRole, ("fail", item.get("file") or "",
                                     int(item.get("line") or 0)))
            self.list.addItem(row)
        for test_id in self.failed:
            row = QListWidgetItem("⚠ " + test_id)
            row.setData(Qt.UserRole, ("id", test_id))
            self.list.addItem(row)
        summary = summarize(code, self.failed, self.found)
        self.title.setText("%s（%.1fs）" % (summary, elapsed))
        self.proc = None

    def _activate(self, item):
        data = item.data(Qt.UserRole) or ()
        if not data:
            return
        kind = data[0]
        if kind == "test":
            self.run([data[1]])
        elif kind == "fail" and data[1]:
            self.jumpTo.emit(str(data[1]), int(data[2] or 1))
        elif kind == "id":
            self.run(failed=[data[1]])  # 双击失败用例 = 只重跑这一条


def _qenv(env):
    """dict -> QProcessEnvironment（缺键也能安全构造）。"""
    from PyQt5.QtCore import QProcessEnvironment
    out = QProcessEnvironment()
    for key, value in (env or {}).items():
        out.insert(str(key), str(value))
    return out


def attach(dialog):
    """把「测试」页挂到编辑器底部面板，返回面板实例。"""
    panel = TestPanel(dialog)
    bottom = getattr(dialog, "bottom", None)
    if bottom is not None:
        bottom.add_extra_tab("测试", panel)
    panel.jumpTo.connect(dialog.open_path_at)
    dialog.test_panel = panel
    return panel
