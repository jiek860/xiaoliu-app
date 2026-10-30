# -*- coding: utf-8 -*-
"""工作台 AI 面板的接线层：后台任务（46.1）与可点击引用（47.3）。

为什么单独一个文件
------------------
`gui/workbench_ai_dock.py` 已经到 600 行上限附近，按批次 35/36 搬
`editor_parts.py` 的老办法，把"接线"代码搬出来：

    AgentDockServiceMixin  后台任务（AgentService + 线程）与代码问答
    LinkPlainTextEdit      只读文本视图，识别 `文件:行` 并可点击跳转

只搬代码不改行为：方法签名、提示文案、按钮状态与原来逐行一致。
"""
from __future__ import annotations

import os
import re

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QPlainTextEdit

try:
    from core.diagnostics import swallowed as _x6_swallowed
except ImportError:  # 独立导入时兜底
    def _x6_swallowed(component, error, context=""):
        return None


class LinkPlainTextEdit(QPlainTextEdit):
    """只读文本：`路径:行` 可点击（双击 / Ctrl+单击）跳转。

    面板里全是纯文本 + appendPlainText，换成 QTextBrowser 会牵动一大片
    调用点；这里只在鼠标事件里认 `文件:行` 的 token，行为完全不变。
    """

    refClicked = pyqtSignal(str, int)
    _REF_RE = re.compile(r"([\w\-./\\]+\.[A-Za-z0-9]{1,8}):(\d{1,6})")

    def mouseDoubleClickEvent(self, e):
        if self._emit_ref(e.pos()):
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if e.modifiers() & Qt.ControlModifier and self._emit_ref(e.pos()):
            return
        super().mousePressEvent(e)

    def _emit_ref(self, pos):
        """光标落在 `路径:行` 上就发信号，返回是否命中。"""
        try:
            cur = self.cursorForPosition(pos)
            text = cur.block().text()
            col = cur.positionInBlock()
            for m in self._REF_RE.finditer(text):
                if m.start() <= col <= m.end() + 1:
                    self.refClicked.emit(m.group(1), int(m.group(2)))
                    return True
        except Exception as e:  # 静默是故意的 - 点击失败不能影响输入
            _x6_swallowed(__name__, e, "dock ref click")
        return False


class AgentDockServiceMixin:
    """AgentDock 的后台执行与代码问答（宿主提供 wb/timeline/service 等）。"""

    # ------------------------------------------------------ 后台任务（46.1）
    def _background_enabled(self):
        try:
            from core.patch_protocol import background_enabled
            return bool(background_enabled(self.wb.trunk))
        except Exception as e:  # 静默是故意的 - 读不到开关就按前台执行
            _x6_swallowed(__name__, e, "background switch")
            return False

    def _start_background(self, goal, open_files):
        """把任务交给 AgentService，再由 AgentServiceWorker 后台消费。"""
        from gui.workbench_ai_dock import resolve_explicit
        try:
            from core.agent_service import get_agent_service
        except Exception as e:
            self.timeline.appendPlainText("[错误] 后台服务不可用: %s"
                                          % str(e)[:200])
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        try:
            self.service = get_agent_service(self.wb.trunk, root=root)
            submitted = self.service.submit(
                goal, open_files=open_files,
                max_rounds=self.rounds_spin.value(),
                explicit=resolve_explicit(goal))
        except Exception as e:  # 静默是故意的 - 出错显示给用户而不是崩
            self.timeline.appendPlainText("[错误] 无法提交后台任务: %s"
                                          % str(e)[:200])
            return
        if not submitted.get("ok"):
            self.timeline.appendPlainText(
                "[错误] %s" % submitted.get("error", "提交失败"))
            return
        self.queue = self.service.queue
        self.current_job_id = submitted["job_id"]
        self.timeline.clear()
        self.timeline.appendPlainText("▶ 目标: " + goal)
        if open_files:
            self.timeline.appendPlainText(
                "  参考文件: " + ", ".join(os.path.basename(f)
                                          for f in open_files))
        self.timeline.appendPlainText(
            "  轮次上限: %d" % self.rounds_spin.value())
        self.timeline.appendPlainText(
            "  执行域: 代码 Agent（后台任务，可切回窗口继续用）")
        self._running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._refresh_queue()
        self._launch_worker()

    def _launch_worker(self):
        from gui.workers import AgentServiceWorker
        self.worker = AgentServiceWorker(self.service, trunk=self.wb.trunk)
        self.worker.event.connect(self._on_service_event)
        self.worker.done.connect(self._on_service_done)
        self.worker.start()

    def _resume_background(self, job):
        """后台模式下续跑：把断点任务重新置为 queued 再起线程。"""
        try:
            from core.agent_service import get_agent_service
        except Exception as e:
            self.timeline.appendPlainText("[错误] 后台服务不可用: %s"
                                          % str(e)[:200])
            return
        root = getattr(self.wb, "root", None) or getattr(
            self.wb.trunk, "base", ".")
        self.service = get_agent_service(self.wb.trunk, root=root)
        self.queue = self.service.queue
        result = self.service.resume(job.get("job_id"))
        if not result.get("ok"):
            self.timeline.appendPlainText("[错误] %s"
                                          % result.get("error", "无法续跑"))
            return
        self.current_job_id = job.get("job_id")
        state = self.queue.checkpoint_of(job)
        self.timeline.clear()
        self.timeline.appendPlainText(
            "↯ 继续任务（从第 %s 轮）" % (state.get("round") or 1))
        self.timeline.appendPlainText("▶ 目标: " + str(job.get("goal") or ""))
        self.timeline.appendPlainText("  执行域: 代码 Agent（后台任务）")
        self._running = True
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("⏸ 暂停")
        self.cancel_btn.setEnabled(True)
        self._refresh_queue()
        self._launch_worker()

    def _on_service_event(self, event, data=None):
        """后台线程的事件在 GUI 线程处理；审批走"事件-应答"而不是弹窗线程。"""
        data = data if isinstance(data, dict) else {}
        if str(event) == "approval" and data.get("request_id"):
            ok = self._approve(data.get("kind"), data.get("payload"))
            if self.service is not None:
                self.service.answer(data.get("request_id"), ok)
            return
        self._handle_event(event, data)

    def _on_service_done(self, result):
        self.worker = None
        self._refresh_queue()
        self._on_done(result)

    # ------------------------------------------------------ 代码问答（47.3）
    def try_code_qa(self, goal):
        """开关开且识别为代码问题时，用本地索引直接回答，返回是否已答。"""
        try:
            from core.agent_router import answer_code_question, code_qa_enabled
            trunk = getattr(self.wb, "trunk", None)
            if not code_qa_enabled(trunk):
                return False
            idx = None
            try:
                idx = trunk.get_workspace_index()
            except Exception as e:  # 静默是故意的 - 没索引就让 core 现场建
                _x6_swallowed(__name__, e, "code qa trunk index")
            root = getattr(self.wb, "root", None) or getattr(trunk, "base", ".")
            result = answer_code_question(goal, root=root, index=idx)
            if not result.get("ok"):
                return False
            self.timeline.clear()
            self.timeline.appendPlainText(str(result.get("answer") or ""))
            self.timeline.appendPlainText(
                "💡 双击（或 Ctrl+单击）引用可跳转到对应代码")
            return True
        except Exception as e:  # 静默是故意的 - 问答失败就走正常执行
            _x6_swallowed(__name__, e, "code qa answer")
            return False

    def open_reference(self, path, line):
        """点击 `文件:行`：在工作台编辑器里打开并定位。"""
        try:
            editor = getattr(self.wb, "_editor", None)
            if editor is not None and hasattr(editor, "open_path_at"):
                editor.open_path_at(path, line)
                return
            if hasattr(self.wb, "open_path"):
                self.wb.open_path(path)
        except Exception as e:  # 静默是故意的 - 跳转失败只提示
            self.timeline.appendPlainText("[错误] 跳转失败: %s" % str(e)[:200])

    # ------------------------------------------------------ 落盘后的编辑器动作（D10）
    _ENTRY_NAMES = ("main", "run", "cli", "app", "demo", "start")

    def _jump_to_entry(self, rel):
        """新文件落盘后直接定位到入口函数，省得用户自己找。"""
        try:
            from core.code import signature
            root = str(getattr(self.wb, "root", None) or ".")
            path = os.path.join(root, str(rel).replace("/", os.sep))
            source = open(path, encoding="utf-8", errors="replace").read()
            line = 0
            hits = [d for d in signature.defs(source)
                    if d["name"] in self._ENTRY_NAMES]
            if hits:
                line = int(hits[0]["line"])
            elif "__main__" in source:
                line = source[:source.index("__main__")].count("\n") + 1
            elif signature.defs(source):
                line = int(signature.defs(source)[0]["line"])
            if line <= 0:
                return
            self.open_reference(path, line)
            self.timeline.appendPlainText(
                "· 已定位到入口：%s:%d" % (rel, line))
        except Exception as e:  # 静默是故意的 - 定位失败不影响已写好的代码
            _x6_swallowed(__name__, e, "jump to entry")

    def after_applied(self, applied):
        """批次 D10：刷新 tab；新文件直接打开并跳到入口，代码立刻可改。"""
        try:
            before = set()
            try:
                before = {str(p) for p in (self.wb.editor_open_files() or [])}
            except Exception as e:
                _x6_swallowed(__name__, e, "read open files")
            for rel in applied or []:
                self.wb.reload_editor_path(rel)
                root = str(getattr(self.wb, "root", None) or ".")
                full = os.path.join(root, str(rel).replace("/", os.sep))
                if full not in before and os.path.exists(full):
                    self._jump_to_entry(rel)
        except Exception as e:  # 静默是故意的 - 刷新失败不影响主流程
            _x6_swallowed(__name__, e, "after applied")

    # ------------------------------------------------------ 多轮澄清（D8）
    _CLARIFY_MAX_ROUNDS = 3

    def _maybe_clarify(self, goal):
        """先追问再执行：返回 ``(flag, goal)``。

        flag::

            ask  —— 已把追问写进时间线/提示条，本次不启动 Agent
            run  —— 槽位补齐（可能是合并后的目标），继续正常执行
            pass —— 路由没要求澄清，原样继续

        用户第二次输入会拼回 ``_pending_clarify_goal`` 再走一次 ``route``，
        最多问 ``_CLARIFY_MAX_ROUNDS`` 轮；再问不出来就按当前理解先跑，
        不把用户卡在对话框里。任何异常都按 pass，保证还能正常执行。
        """
        try:
            from core.nl.clarify import merge_goal
            from core.nl.intent import route
            pending = str(getattr(self, "_pending_clarify_goal", "") or "")
            rnd = int(getattr(self, "_clarify_round", 0) or 0) + 1 if pending else 1
            merged = merge_goal(pending, goal) if pending else goal
            if rnd > self._CLARIFY_MAX_ROUNDS:
                self._pending_clarify_goal = ""
                self._clarify_round = 0
                self.timeline.appendPlainText(
                    "· 追问到第 %d 轮，先按当前理解跑一版" % rnd)
                return "run", merged
            info = route(merged, clarify_round=rnd)
            question = str(info.get("clarify") or "").strip()
            if not question:
                self._pending_clarify_goal = ""
                self._clarify_round = 0
                return ("run" if merged != goal else "pass"), merged
            self._pending_clarify_goal = merged
            self._clarify_round = rnd
            self.hint.setText("还需补充（第 %d 轮）：%s" % (rnd, question))
            self.timeline.appendPlainText("❓ " + question)
            self.timeline.appendPlainText(
                "   把补充写进输入框，再按 Ctrl+Enter 继续")
            return "ask", ""
        except Exception as e:  # 静默是故意的 - 追问失败不能挡住执行
            _x6_swallowed(__name__, e, "maybe_clarify")
            return "pass", goal
