# -*- coding: utf-8 -*-
"""代码编辑器运行器和输出处理。"""
from __future__ import annotations

import os
import sys
import tempfile

from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QPlainTextEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeEditorRunnerMixin:
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
        bottom = getattr(self, "bottom", None)
        if bottom is not None:
            bottom.select(0)          # 运行结果落在「输出」页
        if hasattr(self, "_proc") and self._proc is not None:
            try: self._proc.kill()
            except Exception as e:
                _x6_swallowed(__name__, e)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_out)
        self._proc.finished.connect(self._on_fin)
        self._proc.start(sys.executable.replace("pythonw.exe", "python.exe"), [target])

    def _on_out(self):
        try:
            data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
            self.output.appendPlainText(data.rstrip())
        except Exception as e:
            _x6_swallowed(__name__, e)

    def _on_fin(self, code, status):
        text = self.output.toPlainText()
        # 49.3：运行结束先给结论与可执行提示，再贴退出码 ——
        # 以前只有一行"退出码: 1"，用户还得自己在输出里找异常。
        try:
            from core.code import run_parse, error_hints
            self.output.appendPlainText("📌 " + run_parse.summary(text, code,
                                                                 getattr(self, "root", None)))
            for row in error_hints.lines_for(text):
                self.output.appendPlainText(row)
            self.output.appendPlainText("<<< " + run_parse.exit_text(code))
        except Exception as e:  # 静默是故意的 - 解析失败不影响运行结果
            _x6_swallowed(__name__, e, "run summary")
            self.output.appendPlainText("<<< 退出码: %d" % code)
