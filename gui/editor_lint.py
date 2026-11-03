# -*- coding: utf-8 -*-
"""编辑器的诊断渲染（第 8 批 B5 + 深度⑧⑨）。

三条数据源，一个出口
--------------------
``core/code/lint.py`` 已经算好"怎么调 ruff、怎么解析、怎么合并"，
这里只做 Qt 侧的三件事：

* 深度⑧ **LSP 诊断优先**：语言服务已经在跑，就直接读它的
  ``publishDiagnostics``（类型错误也能报），不为了检查去拉起服务；
* 深度⑨ **实时波浪线**：停手 1.2 秒后把编辑器里的**未保存文本**喂给
  ``ruff --stdin-filename``，所有问题行都画红波浪线（原来只画第一条）；
* 没装 ruff / 没装语言服务时退回 ``ast`` 语法错误，任何环境都能用。

为什么单独成文件
----------------
``gui/code_editor_widget.py`` 贴着 600 行硬上限，这一批要加的东西
（双通道计时器 + ExtraSelection 渲染 + 文档同步）塞不进去。
"""
from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QTextEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # pragma: no cover
    def _x6_swallowed(component, error, context=""):
        return None

from core.code import lint as code_lint

LIVE_DELAY_MS = 1200       # 停手多久才跑一次 ruff（同步子进程，别按键就跑）
MAX_UNDERLINES = 40        # 波浪线最多画几条：再多用户也看不过来
ERROR_COLOR = "#e51400"


class LintEditorMixin:
    """给 ``CodeEditWidget`` 提供"诊断来源合并 + 波浪线 + 实时检查"。"""

    # ---------------------------------------------------------- 初始化
    def _lint_init(self):
        """装实时检查计时器（在 ``CodeEditWidget.__init__`` 末尾调一次）。"""
        self._lint_rows = []
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_DELAY_MS)
        self._live_timer.timeout.connect(self._lint_live)
        try:
            self.textChanged.connect(self._lint_schedule)
        # 静默是故意的 - 挂不上计时器只是没有实时检查，编辑照常
        except Exception as e:
            _x6_swallowed(__name__, e, "hook live lint")

    # ---------------------------------------------------------- 开关
    def _lint_rule(self, name, default=True):
        """读规则（躯干没挂或规则缺失时用 default）。"""
        trunk = getattr(self, "trunk", None)
        if trunk is not None:
            try:
                return bool(trunk.rule(name, default))
            # 静默是故意的 - 读不到规则就用默认值，不打断检查
            except Exception as e:
                _x6_swallowed(__name__, e, "read lint rule")
        return bool(default)

    def _lint_applies(self):
        """只检查 Python：未保存的新标签按 Python 处理，别的语言不误判。"""
        path = getattr(self, "filepath", "") or ""
        if not path:
            return True
        return str(path).lower().endswith((".py", ".pyw"))

    def _lint_schedule(self):
        """打字后重新排期；关掉「实时检查」就只留 ast 快速通道。"""
        if getattr(self, "_live_timer", None) is None:
            return
        if self._lint_rule("编辑.实时检查", True):
            self._live_timer.start()

    def _lint_live(self):
        """慢通道：LSP + 实时 ruff + ast，结果写回问题列表与波浪线。"""
        if not self._lint_applies():
            return []
        rows = self.lint_rows(live=True)
        self.underline_problems(rows)
        self._set_problems(rows)
        return rows

    # ---------------------------------------------------------- 数据源
    def lint_rows(self, live=False):
        """合并三个源（LSP > ruff > ast），返回 ``(行, 列, 规则码, 描述)``。

        读诊断前先把当前文本推给语言服务，否则拿到的是上一次的诊断。
        """
        if not self._lint_applies():
            return []
        self._lint_sync_document()
        path = getattr(self, "filepath", "") or ""
        text = self.toPlainText()
        lsp = self.lsp_problem_rows()
        ruff_rows = None
        if live and not lsp and self._lint_rule("编辑.实时检查", True):
            ruff_rows = code_lint.live_ruff(text, path)
        return code_lint.merge_problems(
            lsp, ruff_rows, code_lint.ast_problems(text))

    def lsp_problem_rows(self):
        """深度⑧：语言服务的诊断（``autostart=False``，不为检查拉起服务）。"""
        if not self._lint_rule("编辑.LSP诊断优先", True):
            return []
        path = getattr(self, "filepath", "") or ""
        if not path:
            return []
        client = self._lsp_client(autostart=False)
        if client is None:
            return []
        try:
            items = client.diagnostics_for(path)
            return code_lint.lsp_rows({path: items}, path)
        # 静默是故意的 - 诊断读失败按"没有"处理，还有 ruff/ast 兜底
        except Exception as e:
            _x6_swallowed(__name__, e, "read lsp diagnostics")
            return []

    def _lint_sync_document(self):
        """把编辑后的文本推给语言服务，它才会重算诊断。"""
        path = getattr(self, "filepath", "") or ""
        if not path or not self._lint_rule("编辑.LSP诊断优先", True):
            return None
        client = self._lsp_client(autostart=False)
        if client is None:
            return None
        try:
            return client.did_change(self.toPlainText(), path)
        # 静默是故意的 - 推文档失败只影响诊断新鲜度
        except Exception as e:
            _x6_swallowed(__name__, e, "lsp did_change")
            return None

    # ---------------------------------------------------------- 渲染
    def underline_problems(self, rows):
        """深度⑨：给**所有**问题行画红波浪线，返回 ExtraSelection 列表。"""
        selections = []
        if not rows:
            self.setExtraSelections([])
            return selections
        fmt = QTextCharFormat()
        fmt.setUnderlineColor(QColor(ERROR_COLOR))
        fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
        doc = self.document()
        for row in rows[:MAX_UNDERLINES]:
            try:
                line = int(row[0])
            except (IndexError, TypeError, ValueError):
                continue
            block = doc.findBlockByNumber(max(0, line - 1))
            if not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)
        return selections
