# -*- coding: utf-8 -*-
"""代码编辑器 AI 修复、diff 预览和 Agent 旅程入口。"""
from __future__ import annotations

import difflib
import os

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton)

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


class CodeEditorAIMixin:
    def _preview_ai_change(self, w, old, new):
        """应用 AI 修改前显示 unified diff，并由用户批准。"""
        d = QDialog(self)
        d.setWindowTitle("AI 修改预览")
        d.resize(920, 620)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("AI 准备修改当前文件。确认后才会写入编辑器："))
        diff = "".join(difflib.unified_diff(
            str(old).splitlines(True), str(new).splitlines(True),
            fromfile="当前内容", tofile="AI 修改后", n=3))
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(diff or "（内容没有变化）")
        view.setStyleSheet(
            "font-family:Consolas,'Microsoft YaHei';font-size:12px;")
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(d.reject)
        row.addWidget(cancel)
        apply_btn = QPushButton("应用修改")
        apply_btn.setStyleSheet(
            "background:#4a9eff;color:white;border:none;border-radius:8px;"
            "padding:7px 14px;")
        apply_btn.clicked.connect(d.accept)
        row.addWidget(apply_btn)
        lay.addLayout(row)
        if d.exec_() != QDialog.Accepted:
            return False
        w._last_ai_old = old
        w.setPlainText(new)
        return True

    def agent_journey_from_editor(self):
        """把当前文件和选中的代码交给统一 Agent 旅程。"""
        w = self._current_edit()
        if not w:
            return
        path = getattr(w, "filepath", "") or ""
        selection = w.textCursor().selectedText()
        root = getattr(self.trunk, "base", None) or os.getcwd()
        goal = "请修改当前文件%s，并运行相关测试。" % (
            (" %s" % path) if path else "")
        if selection.strip():
            goal += " 只针对编辑器中选中的代码片段，不要无关大改。"
        try:
            from gui.agent_journey_dialog import AgentJourneyDialog
            d = AgentJourneyDialog(
                self.trunk, self, root=root,
                open_files=[path] if path else [],
                selection=selection)
            d.goal.setPlainText(goal)
            d.route_combo.setCurrentIndex(1)  # 代码 Agent
            d.show()
            d.raise_()
            self._agent_journey = d
        except Exception as e:
            self.output.appendPlainText("[Agent 旅程] " + str(e)[:300])

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
