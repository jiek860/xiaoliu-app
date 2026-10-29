# -*- coding: utf-8 -*-
"""代码编辑器 AI 修复、diff 预览和 Agent 旅程入口。

批次 46.5：AI 修复改成"局部优先"——
* 有选区就只改选区；
* 没选区就只改光标所在的函数/类；
* 只有连函数都识别不出时才回退整文件，并且把模型返回的完整代码
  压成行级最小 hunk 再落盘，避免"整文件覆盖"丢掉无关代码。
所有改动仍然先过 diff 预览，用户确认后才写入；写入后记一条审计。
"""
from __future__ import annotations

import difflib
import json
import os
import re

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton)

from gui.feedback_states import make_action_links

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:
    def _x6_swallowed(component, error, context=""):
        return None


def _line_offsets(code):
    """每行起始字符下标；``offsets[L-1]`` 是第 L 行的起点。"""
    offsets = [0]
    for line in str(code or "").splitlines(True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _extract_new(text):
    """从模型回复里取替换内容：优先 JSON ``{"new": ...}``，其次代码块。"""
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, dict) and isinstance(data.get("new"), str):
                return data["new"]
        except ValueError:
            pass
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", raw, re.DOTALL)
    return m.group(1) if m else ""


class CodeEditorAIMixin:
    def _preview_ai_change(self, w, old, new, apply=None, title=""):
        """应用 AI 修改前显示 unified diff，并由用户批准。

        ``apply`` 为空时沿用"整文件替换"；内联修复传入局部替换回调。
        """
        d = QDialog(self)
        d.setWindowTitle(title or "AI 修改预览")
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
        row.addWidget(make_action_links([("取消", d.reject)]))
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
        if callable(apply):
            apply()
        else:
            w.setPlainText(new)
        return True

    def _inline_scope(self, w):
        """返回本次要改的片段：选区 > 光标所在函数/类 > 整文件。"""
        code = w.toPlainText()
        cursor = w.textCursor()
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            text = code[start:end]
            if text.strip():
                return {"kind": "selection", "start": start, "end": end,
                        "text": text}
        span = None
        try:
            from core.patch_protocol import function_span
            span = function_span(code, cursor.blockNumber() + 1)
        except Exception as e:  # 静默是故意的 - 识别失败退回整文件
            _x6_swallowed(__name__, e, "inline function span")
        if span:
            offsets = _line_offsets(code)
            first = max(0, int(span["start"]) - 1)
            last = min(int(span["end"]), len(offsets) - 1)
            start, end = offsets[first], offsets[last]
            if end > start:
                return {"kind": "function", "name": span.get("name", ""),
                        "start": start, "end": end, "text": code[start:end]}
        return {"kind": "file", "start": 0, "end": len(code), "text": code}

    def _replace_range(self, w, start, end, new):
        cursor = QTextCursor(w.document())
        cursor.beginEditBlock()
        cursor.setPosition(max(0, int(start)))
        cursor.setPosition(max(0, int(end)), QTextCursor.KeepAnchor)
        cursor.insertText(str(new or ""))
        cursor.endEditBlock()
        w.setTextCursor(cursor)

    def _apply_hunks(self, w, hunks):
        """按行级 hunk 反向替换；old 不唯一就放弃（退回整文件预览）。"""
        code = w.toPlainText()
        hunks = list(hunks or [])
        for hunk in hunks:
            old = str(hunk.get("old") or "")
            if not old or code.count(old) != 1:
                return False
        for hunk in reversed(hunks):
            old = str(hunk.get("old") or "")
            pos = code.find(old)
            self._replace_range(w, pos, pos + len(old),
                                str(hunk.get("new") or ""))
        return True

    def _audit_edit(self, path, before, after, mode, ok=True):
        """内联编辑审计：文件、模式、前后哈希，写 data/code_edits.jsonl。"""
        try:
            from core.patch_protocol import record_edit, text_hash
            record_edit(getattr(self.trunk, "base", None) or os.getcwd(), {
                "kind": "inline_edit", "path": str(path or ""),
                "mode": mode, "ok": bool(ok),
                "before_hash": text_hash(before),
                "after_hash": text_hash(after),
                "before_chars": len(before or ""),
                "after_chars": len(after or ""),
            })
        except Exception as e:  # 静默是故意的 - 审计失败不影响编辑
            _x6_swallowed(__name__, e, "audit inline edit")

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
            old = getattr(self, "_agent_journey", None)
            if old is not None:
                try:
                    if old.isVisible():
                        old.goal.setPlainText(goal)
                        old.route_combo.setCurrentIndex(1)
                        old.show()
                        old.raise_()
                        old.activateWindow()
                        return
                except RuntimeError:
                    self._agent_journey = None
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
        """AI 修复：选区 / 当前函数优先，只有识别不出才回退整文件。"""
        w = self._current_edit()
        if not w:
            return
        scope = self._inline_scope(w)
        code = w.toPlainText()
        before = code
        err = self.output.toPlainText()
        path = getattr(w, "filepath", "") or ""
        self.output.appendPlainText("\n>>> 🤖 正在让 AI 分析并修复（%s）..."
                                    % self._scope_label(scope))
        try:
            llm = self.trunk.modules.get("llm")
            if not llm:
                self.output.appendPlainText("[!] LLM 未连接")
                return
            user_msg = self._fix_prompt(scope, err)
            msgs = [{"role": "system", "content": self._fix_system(scope)}]
            msgs.extend(self._ai_history)
            msgs.append({"role": "user", "content": user_msg})
            reply = str(llm.chat(msgs) or "")
            self._ai_history.append({"role": "user", "content": user_msg})
            self._ai_history.append({"role": "assistant", "content": reply})
            new = _extract_new(reply)
            if not new:
                self.output.appendPlainText("[AI 回复]\n" + reply[:1500])
                return
            if scope["kind"] in ("selection", "function"):
                new = new.rstrip("\n")
                if scope["kind"] == "function" and \
                        code[scope["end"] - 1:scope["end"]] == "\n":
                    new += "\n"
                target = scope["text"].rstrip("\n")
                ok = self._preview_ai_change(
                    w, target, new, title="AI 局部修改预览",
                    apply=lambda: self._replace_range(
                        w, scope["start"], scope["end"], new))
                mode = scope["kind"]
            else:
                hunks = []
                try:
                    from core.patch_protocol import minimal_hunks
                    hunks = minimal_hunks(code, new)
                except Exception as e:  # 静默是故意的 - 退化为整文件预览
                    _x6_swallowed(__name__, e, "minimal hunks")

                def _apply_full(text=new, parts=hunks):
                    if not (parts and self._apply_hunks(w, parts)):
                        w.setPlainText(text)

                ok = self._preview_ai_change(
                    w, code, new, title="AI 整文件修改预览",
                    apply=_apply_full)
                mode = "minimal" if hunks else "file"
            if ok:
                self._audit_edit(path, before, w.toPlainText(), mode)
                self.output.appendPlainText(
                    "[✓] AI 已按%s修改，点 ▶ 运行再试" % self._scope_label(scope))
        except Exception as e:
            self.output.appendPlainText("[AI 修复失败] " + str(e)[:300])

    @staticmethod
    def _scope_label(scope):
        kind = str((scope or {}).get("kind") or "file")
        if kind == "selection":
            return "选中片段"
        if kind == "function":
            return "函数 %s" % (scope.get("name") or "")
        return "整文件"

    @staticmethod
    def _fix_system(scope):
        if scope.get("kind") == "selection":
            return ("你是 Python 修复专家。只修改用户选中的片段，"
                    "只输出严格 JSON：{\"new\":\"替换后的片段\",\"reason\":\"原因\"}。"
                    "不要输出整文件，不要 Markdown。")
        if scope.get("kind") == "function":
            return ("你是 Python 修复专家。只修改函数 %s，"
                    "只输出严格 JSON：{\"new\":\"该函数替换后的完整代码\","
                    "\"reason\":\"原因\"}。不要输出整文件，不要 Markdown。"
                    % (scope.get("name") or ""))
        return ("你是 Python 修复专家。只输出严格 JSON："
                "{\"new\":\"修复后的完整文件\",\"reason\":\"原因\"}，不要 Markdown。")

    @classmethod
    def _fix_prompt(cls, scope, err):
        return ("下面是要修复的代码片段（范围：%s）和它运行时的输出/错误。"
                "请找出 bug 并按系统要求返回替换内容。\n\n"
                "=== 代码 ===\n%s\n\n=== 运行输出 ===\n%s"
                % (cls._scope_label(scope), scope.get("text") or "",
                   (err[-2000:] if err else "(无输出)")))
